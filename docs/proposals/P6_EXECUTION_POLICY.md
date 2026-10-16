# P6 production execution policy: proposal

Status: **APPROVED and FROZEN on 2026-10-16** (DECISIONS section 36), as
drafted, with threshold option 2 (common 0.30; 0.20, 0.40 and 0.65 reported).

- The values live in `configs/phase6_execution.json` (`pair-execution-policy-v2`,
  FROZEN) and `configs/phase6_execution_sensitivities.json`.
- The interim `configs/phase6_execution_proposed.json` was removed.
- The text below is the proposal as approved.
- Re-running the diagnostics with the exact-XNYS-session ADV rule reproduced
  every figure below.

**Timing and information used.** This proposal was written after the
2022–2023 assessment forecasts had already been observed in earlier
development work. It was also written after the P6 selection inventory showed
that Model A and Model B select no assessment event at 0.65. No backtest
return, simulated price path or supervised label has been computed or read for
it. The numbers below come from two kinds of input:

- **Cited literature.** Every figure was read in the primary text unless it is
  marked *secondary*.
- **Target-blind diagnostics.** These come from
  `structural-break-backtest policy-diagnostics`. They read only data dated
  2006-01-01…2021-12-31, from the provisional pack (`UNACCEPTED_ENGINEERING`),
  and never load label columns. They must be re-run on the official snapshot
  before the freeze.

## 1. Summary of the proposal

| Assumption | Proposed headline | Sensitivities (all reported, none selected) |
|---|---|---|
| Trading cost per entry and per exit turnover | **5 bps** | 2.5 / 10 / 20 bps (the existing predeclared grid) |
| Short borrow (annual, on entry short notional, held open-to-open sessions / 252) | **1.0 % p.a.** | 0 / 3 / 10 % (the existing predeclared grid) |
| Positive-beta ceiling (0 < β ≤ c) | **c = 3** | c = 2, 5, none |
| Liquidity floor: minimum-leg 20-session mean dollar volume at the signal close | **≥ $5 M** | none, $1 M, $10 M |
| Share-price floor | **none** (§5) | none |
| Price adjustment | Yahoo retrospective adjusted close; adjusted open = open × adj_close / close from the same row | none; disclosed limitation |
| A/B trading threshold | **Owner decision, §7** | §7 |
| Horizon | 20 sessions | 10 / 30 sessions (existing) |
| Economic uncertainty | Freeze the fixture policy: 2,000 paired calendar-month draws, seed 5557, intervals only with ≥ 12 contributing months | none |
| Portfolio (secondary) | Freeze the fixture policy: 25 % of NAV gross per entry, gross admission cap 1, one position per pair, zero cash yield, no financing | none |

Cost and borrow scenarios cross into the same 4 × 4 grid for every rung, with no
winner selected. Every eligibility gate is shared execution eligibility,
applied after selection and identically to all five rungs. None of them
changes the v2 forecasting population.

## 2. Trading cost: 5 bps per turnover side

Evidence:

- **Hagströmer**, *Bias in the Effective Bid-Ask Spread* (working paper,
  Sept 2019, Table 1, p. 18). For S&P 500 constituents over 7–11 Dec 2015, the
  dollar-weighted mean midpoint effective spread is 3.22 bps (median 3.02, 95th
  percentile 7.78). The micro-price effective spread is 2.73 bps, and the paper
  finds the midpoint measure overstates the true cost by 18 % on average. The
  effective spread is a round-trip measure, so a small one-way market order
  costs about half of it, roughly 1.4–1.6 bps.
- **Frazzini, Israel and Moskowitz**, *Trading Costs* (SSRN 3229719, 2018).
  They use 1.7 trillion dollars of live institutional executions from 21
  developed markets, 1998–2016. The abstract finds costs an order of magnitude
  below earlier academic estimates. *Secondary*: summaries report about 9 bps
  average market impact for large-cap trades. The SSRN text was not accessible
  (HTTP 403), so this figure is only the rationale for the 10 bps sensitivity
  and is not cited as a primary number.
- **Do and Faff**, *Are pairs trading profits robust to trading costs?*,
  *Journal of Financial Research* 35(2), 2012, 261–287. They model commissions,
  market impact and short-selling fees for US pairs trading over 1963–2009, and
  profits survive at much more modest levels. This is context for why costs
  must be explicit, not a parameter source.

Proposal:

- **Headline 5 bps per side.** This is about three times the 2015 large-cap
  half-spread. The margin covers wider spreads in 2006–2010 (including 2008),
  small-order fees, and modest impact for the scale-free unit notional that
  each event trades.
- **2.5 bps** is close to the pure half-spread lower bound.
- **10 bps** approximates large-institution market impact.
- **20 bps** is a stress case for crisis spreads.
- All four values are the existing predeclared grid, so nothing new is
  introduced.
- Per-side costs apply to actual entry and actual exit gross turnover, as now.

Why the per-stock spread is not estimated from our own OHLC data: Ardia,
Guidotti and Kroencke (2024, *JFE* 161, 103916; 2021 working paper p. 5) find
that, with daily data, all such estimators are upward biased for highly liquid
large caps with tiny spreads. EDGE is unbiased only down to about 0.10–0.30 %
with one-year windows. Our roster is all large caps, so a daily-OHLC estimate
would overstate costs and add noise rather than information.

## 3. Short borrow: 1.0 % per year headline

Evidence:

- **D'Avolio**, *The market for borrowing stock*, *JFE* 66 (2002), 271–306,
  p. 273, using 18 months (Apr 2000–Sep 2001) of lender data:
  - 91 % of stocks lent cost under 1 % p.a.;
  - these general-collateral stocks have a value-weighted mean fee of 17 bps;
  - "S&P 500 constituents … are almost always general collateral";
  - the 9 % of "specials" average 4.3 %.
- **Engelberg, Reed and Ringgenberg**, *Short-Selling Risk* (2014 working
  paper, p. 8; published *JF* 73(2), 2018), using Markit data for 4,500+ US
  equities over Jul 2006–Dec 2011: the median loan fee is 11 bps p.a., the mean
  85 bps and the 99th percentile 1,479 bps.

Proposal:

- **Headline 1.0 % p.a.** This is about six times the general-collateral fee
  and above the all-stock mean of 0.85 %, which includes small caps and
  specials. It is deliberately conservative because historical borrow fees and
  availability for our names are not observed.
- **Sensitivities: 0 / 3 / 10 %** (the existing grid). 10 % approximates a
  persistent special.
- 1.0 % is new relative to the fixture grid. If you prefer to stay strictly
  inside the predeclared values, use **3 %** as the headline.
- Disclosed limitations:
  - no rebate is earned on short proceeds, and there is no margin or
    financing model;
  - hard-to-borrow status, recalls and availability are not modelled, and
    every short is assumed to be available.

## 4. Positive-beta ceiling: c = 3

Under w_A = −s/(1+β) and w_B = sβ/(1+β), the notional ratio between the legs
equals β. Writing s for the signal sign, this means:

- c = 3 caps leg imbalance at 3:1;
- above that, the "pair" is mostly a single-name position, and the hedge rests
  on a poorly identified slope.

Target-blind diagnostics (h20 episode events, 2006–2021, n = 25,513):

- 2,685 (10.5 %) have β ≤ 0 and are ineligible under any ceiling.
- The positive-β median is 0.76; the 95th percentile is 1.92 and the 99th 3.08.
- Events above each ceiling: c = 2: 999 (3.9 %); c = 3: 246 (1.0 %);
  c = 5: 62 (0.24 %).
- The ACTIVE raw-crossing subset is similar (n = 3,872: 42 above 3, 11 above 5).

c = 3 sits at the economic 3:1 bound and roughly at the 99th percentile. It is
chosen without outcome information. 2, 5 and "none" are reported as
sensitivities.

## 5. Eligibility floors

- **Liquidity: minimum-leg 20-session mean dollar volume ≥ $5 M**, over the
  20 sessions ending at the signal close (admissible at the signal).
  - `dollar_volume` = split-adjusted close × split-adjusted volume, so it is
    split-invariant.
  - 2006–2021 h20 episode events: median $96.6 M; 1st percentile $0.6 M.
  - Events below each floor: $1 M: 310 (1.2 %); $5 M: 629 (2.5 %);
    $10 M: 1,237 (4.8 %); $25 M: 3,525 (13.8 %).
  - The floor keeps the 5 bps large-cap cost assumption credible. It is
    applied identically to every rung.
- **No share-price floor.** Yahoo's raw `close` is retrospectively
  split-adjusted through the 2026 capture date. Splits after 2023 are not
  visible in our 2004–2023 `stock_splits` column, so historical price levels
  cannot be reconstructed reliably, and a $5 floor would exclude the wrong
  names. The $5 screen targets small, hard-to-borrow stocks, which our
  large-cap roster does not contain. Engelberg et al. (p. 7) drop stocks below
  $5, and D'Avolio (p. 273) finds hard-to-short names concentrated below $5.
- **Implementation consequence** (after approval): `ExecutionConfig` gets a
  versioned schema `pair-execution-policy-v2` with `min_leg_adv20_usd`. The
  adapter supplies the signal-time ADV, and the engine returns
  `NOT_ENTERED / ILLIQUID_LEG`.

## 6. Price adjustment and corporate actions

- Closes are the Yahoo adjusted close; opens are open × adj_close / close from
  the same capture row (implemented, Decision 35).
- Dividends sit in the total-return basis of both legs. The short leg
  therefore pays the dividend implicitly, which matches the manufactured
  dividend described in D'Avolio §2.1.3.
- The data are retrospective rather than vintage. There is no delisting
  settlement, because the surviving 250-issuer roster has none. Both are
  disclosed limitations.

## 7. A/B trading threshold (owner decision)

Facts, using calibration-period (2020–2021) calibrated scores, target-blind:

| Model | ACTIVE events n | Max | p90 | ≥ 0.2 | ≥ 0.3 | ≥ 0.4 | ≥ 0.5 | ≥ 0.65 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| logistic A | 303 | 0.594 | 0.289 | 98 | 29 | 9 | 3 | **0** |
| logistic B-both | 303 | 0.557 | 0.301 | 106 | 31 | 11 | 1 | **0** |
| xgboost A | 303 | 0.465 | 0.282 | 87 | 23 | 4 | 0 | 0 |
| xgboost B-both | 303 | 0.502 | 0.297 | 110 | 30 | 7 | 1 | 0 |

Across all 3,762 calibration events, nothing reaches 0.65 for any model; the
maxima are 0.606 and 0.641. The calibrated scale has a median near 0.10, so 0.65
selects nothing in any development period. The empty assessment A/B rungs
follow from the threshold, not from assessment outcomes.

Options, all applied as one common threshold to A and B:

1. **Keep 0.65.** The A/B economic rungs are reported as empty, and A versus B
   is evaluated only through the broad forecasting comparison.
2. **Common threshold 0.30** (recommended if you want informative A/B rungs).
   On 2020–21 ACTIVE events this selects 29 (A) and 31 (B) of 303, about the
   top decile. Report 0.20 and 0.40 as sensitivities, and keep 0.65 reported
   alongside.
3. **Per-model quantile thresholds** (equal selection rates). This breaks the
   "same declared threshold" rule in spec §3 and would need an explicit
   amendment. Not recommended.

Options 2 and 3 are post-hoc amendments made after the empty 0.65 rungs were
observed. Whichever is chosen must be recorded with that timing, and its
assessment results labelled post-hoc development. Choose before any return is
computed.

## 8. What happens after approval

1. Record the approved values as a DECISIONS amendment with timing.
2. Add the `pair-execution-policy-v2` schema (liquidity floor) and its tests.
3. Freeze `configs/phase6_execution.json` → `status: FROZEN`, and give the
   ladder policy its threshold.
4. Re-run the diagnostics on the official snapshot.
5. Step C: build the accepted experiment manifest and immutable persistence.
   Only then compute the first genuine development-assessment economic
   numbers.

## Sources

- Hagströmer, B. (2019). Bias in the Effective Bid-Ask Spread (working paper, 25 Sep 2019). https://www.hec.edu/sites/default/files/documents/overestEspr-v12.pdf. Journal version not checked here.
- D'Avolio, G. (2002). The market for borrowing stock. *Journal of Financial Economics* 66, 271–306. https://www.johnhcochrane.com/s/davolio_borrowing_stock_JF.pdf
- Engelberg, J., Reed, A., Ringgenberg, M. (2018). Short-Selling Risk. *Journal of Finance* 73(2), 755–786; working paper https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/03/riggenberg.pdf
- Frazzini, A., Israel, R., Moskowitz, T. (2018). Trading Costs. SSRN 3229719. https://papers.ssrn.com/abstract=3229719
- Do, B., Faff, R. (2012). Are pairs trading profits robust to trading costs? *Journal of Financial Research* 35(2), 261–287. https://strathprints.strath.ac.uk/41722/
- Ardia, D., Guidotti, E., Kroencke, T. (2024). Efficient estimation of bid–ask spreads from open, high, low, and close prices. *Journal of Financial Economics* 161, 103916. Working paper: https://acfr.aut.ac.nz/__data/assets/pdf_file/0016/570202/Efficient_Estimation_of_Bid_Ask_Spreads_from_OHLC_Prices-39.pdf

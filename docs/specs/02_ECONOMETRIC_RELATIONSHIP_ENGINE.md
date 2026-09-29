# Econometric Relationship Engine

> **Agent-use specification.** Canonical implementation decisions are in [`../DECISIONS.md`](../DECISIONS.md). This Markdown is the coding-agent source of truth for this subsystem. The PDF in `docs/PDFs/` is archival/human-readable only.

# 1. Engine boundary and end-to-end workflow

## 1.1 Responsibility

The relationship engine receives cleaned daily price histories and a fixed pair registry. It determines whether each pair has a statistically defensible long-run relationship, estimates that relationship point-in-time, converts the fitted residual into a standardised divergence state, computes stability diagnostics, and determines whether the pair is ACTIVE, WATCH, or RETIRED.

## 1.2 Complete deterministic workflow

| Step | Operation | Primary output |
| --- | --- | --- |
| 1 | Load pair A/B price history and fixed pair orientation. | Aligned adjusted-close histories and data-quality flags. |
| 2 | Transform adjusted prices to log levels; compute log returns / first differences for diagnostics. | y_t, x_t, Δy_t, Δx_t. |
| 3 | Check integration order of each log-price series. | ADF/KPSS diagnostics; I(1)-compatibility flag. |
| 4 | Estimate long-run relation by OLS inside the 504-day formation window. | α-hat, β-hat, OLS residuals. |
| 5 | Run augmented Engle-Granger cointegration test. | Cointegration t-statistic and MacKinnon p-value. |
| 6 | Construct the residual spread and freeze relationship parameters for the signal month. | Cointegration vector, spread mean/std. |
| 7 | Estimate mean-reversion speed and stability statistics. | AR(1) ρ, half-life, beta drift, correlations, volatility, crossings. |
| 8 | Assign pair lifecycle state. | ACTIVE / WATCH / RETIRED. |
| 9 | During the signal month, compute daily spread and z-score using frozen parameters. | Daily pair-state table. |
| 10 | When an ACTIVE pair crosses the divergence threshold, create one event. | Event row and frozen feature timestamp. |
| 11 | Look forward only for label construction. | Success / failure / timeout label for ML training. |

Separation from downstream AI VIX, market returns, sector returns, NLP events, sentiment, SHAP, and agent findings are not regressors in the core cointegration equation. They are downstream ML/context features. This keeps the econometric relationship transparent and prevents the classical model from expanding into the main AI contribution.

# 2. Required data, variables, and transformations

## 2.1 Minimum data required by the relationship engine

| Data item | Source table / field | Use in econometrics |
| --- | --- | --- |
| Trading date | curated market prices: trading_date | Calendar alignment and point-in-time windows. |
| Adjusted close for leg A | adj_close for y_ticker | Log price y_t; corporate-action-consistent level. |
| Adjusted close for leg B | adj_close for x_ticker | Log price x_t. |
| Volume | volume for each leg | Not a regressor; optional liquidity gate and downstream feature. |
| Pair registry | pair_id, y_ticker, x_ticker, sector, active dates | Fixes economic pairing and OLS orientation ex ante. |
| Corporate-action audit | dividends, stock_splits | Quality control; adjusted prices remain modelling input. |

## 2.2 Price-level transformation

$$
y_t=\ln(P^{A,adj}_t),\qquad x_t=\ln(P^{B,adj}_t)
$$

$$
\Delta y_t=y_t-y_{t-1}=\ln\left(\frac{P^{A,adj}_t}{P^{A,adj}_{t-1}}\right),\qquad
\Delta x_t=x_t-x_{t-1}.
$$

Use strictly positive corporate-action-adjusted closing prices. For each security, transform the adjusted closing price to a natural logarithm. Log levels are the inputs to the long-run relationship; log differences are the daily continuously compounded returns used for integration and correlation diagnostics.

## 2.3 Calendar alignment

- Take the inner intersection of trading dates for the two securities.
- Never forward-fill missing equity prices across non-trading days or missing observations.
- Require a complete formation window after alignment; the default is 504 valid common trading days.
- A missing or non-positive adjusted close invalidates that observation before taking logs.

# 3. Pair orientation and pre-estimation eligibility

## 3.1 Pair orientation is fixed, not searched

Engle-Granger is not perfectly symmetric because the first-stage OLS regression treats one series as dependent. To avoid choosing the orientation that looks best in-sample, every pair receives a fixed y_ticker and x_ticker in the pair registry before backtesting. The same orientation is used throughout historical reconstruction, model training, test evaluation, and the UI. Why this matters Running both A-on-B and B-on-A and then choosing the stronger result would add an unrecorded model-selection step and increase data-snooping risk. A fixed orientation is reproducible and auditable.

## 3.2 Economic pre-screen

| Gate | Baseline rule | Purpose |
| --- | --- | --- |
| Economic similarity | Manually curated same-sector / same-sub-industry pair. | Avoid blind combinatorial pair mining. |
| History | At least 504 aligned observations before an estimation date. | Ensures full formation window. |
| Price validity | All modelling prices finite and > 0. | Required for log transformation. |
| Liquidity | Minimum volume/liquidity policy from data layer. | Prevents obviously non-tradable research cases. |
| Integration compatibility | Both log-price series plausibly I(1). | Required by Engle-Granger framework. |

# 4. Integration-order diagnostics

## 4.1 Why the I(1) condition is checked

The augmented Engle-Granger test assumes the variables entering the cointegrating relationship are integrated of order one, I(1): their levels are non-stationary but their first differences are stationary. The engine therefore performs a diagnostic on each log price before using the pair as an ACTIVE cointegration candidate.

## 4.2 Augmented Dickey-Fuller test

$$
\Delta q_t=a+\gamma q_{t-1}+\sum_{j=1}^{p}\phi_j\Delta q_{t-j}+\varepsilon_t,
$$
where $q_t$ is $y_t$ or $x_t$.

For q_t equal to y_t or x_t, the ADF null is a unit root. In levels, failure to reject is consistent with non-stationarity. In first differences, rejection of the unit-root null is consistent with stationarity. The baseline uses a constant and automatic lag selection by AIC.

## 4.3 KPSS cross-check

As a robustness diagnostic, KPSS reverses the null: stationarity is the null. Combining ADF and KPSS reduces reliance on a single test. KPSS is not required for the Engle-Granger computation itself but is useful for classifying ambiguous series.

| Series state | ADF level | KPSS level | ADF first difference | Interpretation |
| --- | --- | --- | --- | --- |
| Preferred I(1) pattern | Do not reject unit root | Reject stationarity | Reject unit root | Compatible with Engle-Granger. |
| Clearly I(0) | Reject unit root | Do not reject stationarity | - | Do not use as standard I(1)- I(1) pair. |
| Ambiguous | Tests conflict | Tests conflict | Investigate | WATCH / diagnostic flag; do not force a conclusion. |
| Potential I(2) | Do not reject | Reject | Do not reject | Incompatible with baseline engine. |

Implementation rule The integration diagnostics are a validity check, not a search for whichever p-value makes the pair eligible. Test specification and significance level are fixed globally.

# 5. Engle-Granger step 1: long-run OLS relationship

## 5.1 Cointegrating regression

$$
y_t=\alpha+\beta x_t+u_t,\qquad t=T-W+1,\ldots,T,\quad W=504.
$$

Inside each formation window, estimate a constant-only long-run relationship between the two log adjusted prices: Here W=504 trading days. The parameters are estimated by ordinary least squares. The intercept α captures the average level offset; β is the cointegrating coefficient used to construct the residual spread. With log prices, β is best interpreted as a long-run elasticity / relative exposure coefficient, not literally as the number of shares to short.

## 5.2 OLS objective

$$
(\hat\alpha,\hat\beta)=\arg\min_{\alpha,\beta}\sum_{t\in\mathcal W_T}(y_t-\alpha-\beta x_t)^2.
$$

## 5.3 Estimated residuals

$$
\hat u_t=y_t-\hat\alpha-\hat\beta x_t.
$$

The residual is the candidate equilibrium error. Cointegration requires these residuals to be stationary even though y_t and x_t individually are non-stationary. A high OLS R-squared is not itself evidence of cointegration and is not used as the eligibility criterion. No extra regressors in the core equation SPY, sector ETFs, VIX, volume, valuation ratios, and NLP variables do not enter this OLS equation. The relationship engine intentionally remains a two-price model. Those other variables are used downstream as ML features or risk/context diagnostics.

# 6. Engle-Granger step 2: residual stationarity / cointegration test

## 6.1 Residual ADF concept

$$
\Delta\hat u_t=\delta\hat u_{t-1}+\sum_{j=1}^{p}\psi_j\Delta\hat u_{t-j}+e_t.
$$

The second Engle-Granger step asks whether the estimated equilibrium error is stationary. Conceptually, the residual is tested with an augmented unit-root regression: The null is no cointegration (residual contains a unit root). Rejection supports a stationary residual and therefore a cointegrating relationship. Because the residual is estimated in a first-stage regression, ordinary ADF critical values are not the correct Engle-Granger critical values.

## 6.2 Production test statistic and p-value

Use statsmodels.tsa.stattools.coint(y, x, trend="c", method="aeg", autolag="aic"). The function implements the augmented Engle-Granger two-step test and returns the cointegration test statistic together with MacKinnon approximate p-values/critical values appropriate to the cointegration setting. The baseline eligibility starting rule is p_coint < 0.05.

| Output | Stored field | Use |
| --- | --- | --- |
| Cointegration t-statistic | coint_tstat | Continuous relationship-quality feature and diagnostic. |
| MacKinnon p-value | coint_pvalue | Primary statistical eligibility gate. |
| Critical values | coint_crit_1pct/5pct/10pct | Audit and UI diagnostics. |
| Lag-selection configuration | eg_autolag | Reproducibility; baseline AIC. |

Important implementation detail Do not take the p-value returned by a generic adfuller() call on the first-stage residuals and treat it as the Engle-Granger cointegration p-value. The production gate uses coint(), which applies the appropriate MacKinnon cointegration distribution.

# 7. Cointegration vector, equilibrium spread, and hedge coefficient

## 7.1 Cointegration vector

$$
\hat b=(1,-\hat\beta),\qquad s_t=y_t-\hat\alpha-\hat\beta x_t.
$$

The fitted long-run relation can be written as a stationary linear combination. Ignoring the intercept for vector notation, the two-asset cointegration vector is proportional to (1, -β-hat). The intercept is stored separately.

## 7.2 Spread interpretation

- s_t > 0: leg A is high relative to the fitted relationship with leg B.
- s_t < 0: leg A is low relative to the fitted relationship.
- s_t near the formation equilibrium: the pair is close to its estimated long-run relation.
- The spread is a statistical state variable. It is not itself a guaranteed arbitrage profit.

## 7.3 Relationship coefficient versus trading weights

The econometric engine stores β-hat as the relationship coefficient. The backtester may use it to form a beta-scaled relative return, but actual executable share quantities depend on current prices, capital, borrow constraints, and transaction costs. Those implementation choices belong to the backtesting/execution layer, not to the cointegration test.

# 8. Point-in-time rolling estimation design

## 8.1 Formation and signal periods

$$
\mathcal W_T=\{T-W+1,\ldots,T\},\qquad W=504.
$$

The relationship is re-estimated monthly. On each estimation date T, the engine uses only the previous 504 common trading observations. The resulting parameters become effective from the next trading session and remain frozen until the next scheduled re-estimation.

## 8.2 Why parameters are frozen between re-estimations

- A divergence should be measured against a relationship known before the signal, not a regression that immediately adapts to the divergence.
- Freezing α-hat and β-hat prevents the model from partially fitting away the event it is supposed to detect.
- Monthly snapshots make historical reconstruction and app displays deterministic and easy to audit.

## 8.3 Effective-time convention

| Timestamp | Rule |
| --- | --- |
| Estimation close T | Formation window ends at T close. Fit and diagnostics are computed after the close. |
| Effective start | The new snapshot is first eligible for signals on the next trading day T+1. |
| During signal month | Use the same α-hat, β-hat, formation spread mean/std, and status until the next effective snapshot. |
| Historical backtest | Each event joins to the latest snapshot with effective_start <= event_date; never to a future monthly estimate. |

# 9. Spread standardisation and daily pair state

## 9.1 Formation spread moments

$$
\hat\mu_{s,T}=\frac{1}{W}\sum_{t\in\mathcal W_T}\hat u_t,
\qquad
\hat\sigma_{s,T}=\sqrt{\frac{1}{W-1}\sum_{t\in\mathcal W_T}(\hat u_t-\hat\mu_{s,T})^2}.
$$

From the in-window OLS residuals, store the formation spread mean and standard deviation. With an intercept, the residual mean is numerically close to zero, but it is stored explicitly for transparency and reproducibility.

## 9.2 Out-of-sample daily spread and z-score

$$
s_\tau=y_\tau-\hat\alpha_T-\hat\beta_Tx_\tau,
\qquad
z_\tau=\frac{s_\tau-\hat\mu_{s,T}}{\hat\sigma_{s,T}}.
$$

For any signal date τ after the estimation date and before the next re-estimation, calculate the spread with the frozen coefficients and standardise it with the frozen formation moments: Why the standardisation is frozen Recomputing the mean and variance with future signal-period observations would allow the reference distribution to adapt to the divergence. The baseline therefore uses formation-window moments until the next monthly estimation snapshot.

## 9.3 Daily state variables

| Variable | Definition / transformation |
| --- | --- |
| spread | Current s_tau from frozen α-hat and β-hat. |
| z_score | Current spread in formation standard deviations. |
| spread_velocity_1d | s_tau - s_(tau-1). |
| z_velocity_1d | z_tau - z_(tau-1). |
| abs_z | \|z_tau\|. |
| days_since_zero_cross | Trading days since spread last changed sign. |
| pair_status | ACTIVE / WATCH / RETIRED from the latest monthly snapshot. |

# 10. Mean-reversion speed and half-life

## 10.1 AR(1) spread model

$$
s_t=c+\rho s_{t-1}+\eta_t,
\qquad
h_{1/2}=-\frac{\ln 2}{\ln\rho}\quad\text{for }0<\rho<1.
$$

Half-life is estimated as a descriptive relationship-quality statistic using the formation-window spread. Fit a first-order autoregression: For a stable positive autoregressive coefficient 0 < ρ < 1, the implied half-life is the number of trading days required for a deviation to decay by one half under the AR(1) approximation:

## 10.2 Validity rules

| Case | Treatment |
| --- | --- |
| 0 < ρ < 1 | Store finite half-life. |
| ρ >= 1 | No mean-reverting AR(1) interpretation; half-life set null/invalid and relationship flagged. |
| ρ <= 0 | Oscillatory / very fast sign switching; do not force half-life formula; flag for review. |
| Very long half-life | Relationship may be statistically cointegrated but too slow for the 10-day event horizon; retain as feature/diagnostic rather than silently excluding unless policy specifies a gate. |

## 10.3 Equivalent error-correction representation

$$
\Delta s_t=\kappa+\phi s_{t-1}+\eta_t,
\qquad \phi=\rho-1.
$$

Negative φ corresponds to error correction. The project can store φ as an alternative mean-reversion-speed feature. A full VECM is not required for the core two-asset engine; the simple AR(1) spread diagnostic is sufficient and keeps the econometrics supporting rather than dominant.

# 11. Relationship stability diagnostics

## 11.1 Core diagnostics computed each monthly snapshot

For hedge-ratio drift use

$$
\mathrm{beta\_drift}_T=\frac{|\hat\beta_T-\hat\beta_{prev}|}{\max(|\hat\beta_{prev}|,\varepsilon)}.
$$

| Diagnostic | Mathematical definition / rule | Role |
| --- | --- | --- |
| Cointegration history | Current and previous coint_tstat / p-value. | Primary validity history. |
| Return correlation 20d / 60d | Corr(Δy, Δx) over trailing 20/60 common days. | Short/medium co-movement context; not a substitute for cointegration. |
| Beta drift | \|β_T - β_prev\| / max(\|β_prev\|, ε). | Detect changing long-run exposure. |
| Spread volatility | Std(s) over trailing 20d; ratio to formation σ_s. | Detect sudden instability. |
| Zero crossings | Count of sign changes in s over trailing 252d. | Empirical evidence that equilibrium is revisited. |
| Recency of crossing | Days since latest sign change. | Identifies spreads drifting one-sided for long periods. |
| Half-life | AR(1) implied h_1/2. | Mean-reversion speed feature. |
| Formation residual range | max(z_in) - min(z_in). | Scale / tail diagnostic. |

## 11.2 Optional structural-stability test

CUSUM can be computed on the first-stage OLS residuals as a secondary warning flag. Its null is parameter stability. This is not the project's main structural-break detector and should not override the AI evidence layer; it is an econometric diagnostic only. Implementation: statsmodels.stats.diagnostic.breaks_cusumolsresid(resid, ddof=2). Store the statistic, p-value, and 1%/5%/10% critical values. A low p-value raises a stability warning. Avoid diagnostic overload Do not add every possible time-series test. The engine should expose a small set of interpretable, pre-specified statistics that are either used as gates, ML features, or visible diagnostics. Tests with no downstream role increase complexity without improving the research design.

# 12. Pair lifecycle and gating rules

## 12.1 Monthly status assignment

| Status | Core rule | New divergence events? |
| --- | --- | --- |
| ACTIVE | Full history; I(1)-compatible; coint p-value below policy threshold; no hard data-quality failure. | Yes. |
| WATCH | One monthly snapshot fails cointegration or a material stability/data-quality warning is triggered. | No in baseline; UI may display relationship deterioration. |
| RETIRED | Two consecutive monthly invalid snapshots, delisting/major transformation, or persistent unusable data/liquidity. | No. |

## 12.2 Default hard versus soft gates

| Type | Examples | Effect |
| --- | --- | --- |
| Hard gate | Insufficient 504-day history; invalid prices; series clearly not I(1); coint p >= 0.05; missing current price. | Pair cannot be ACTIVE. |
| Soft diagnostic | Large beta drift; long half-life; elevated spread volatility; low crossing frequency; CUSUM warning. | Stored and surfaced; can move pair to WATCH by pre-specified policy or feed downstream ML. |
| Manual lifecycle flag | Merger completion, delisting, ticker replacement, permanent corporate restructuring. | RETIRED with reason code and effective date. |

No p-value shopping The 5% threshold is a baseline configuration. If the team compares 1%, 5%, and 10%, the choice is made on training/validation only and locked before the final test period.

# 13. Divergence-event generation and econometric labels

## 13.1 Event trigger

$$
|z_t|\ge z_{entry},\qquad |z_{t-1}|<z_{entry},\qquad \mathrm{pair\_status}_t=\mathrm{ACTIVE}.
$$

The relationship engine creates an event only when an ACTIVE pair enters the divergence region from inside it. This avoids treating every day of the same prolonged divergence as a new independent observation. Baseline z_entry = 2.0. Store direction d_t = sign(z_t): +1 means A is high relative to B; -1 means A is low relative to B.

## 13.2 Event resolution and target label

Let $s_i=\operatorname{sign}(z_{i,t_0})$. Define

$$
\tau_i^{conv}=\min\{h\in\{1,\ldots,H\}:|z_{i,t_0+h}|\le z_{exit}\},
$$

$$
\tau_i^{stop}=\min\{h\in\{1,\ldots,H\}:s_i z_{i,t_0+h}\ge z_{stop}\},
$$

and

$$
y_i=\mathbf{1}[\tau_i^{conv}\le H\ \text{and}\ \tau_i^{conv}<\tau_i^{stop}].
$$

Baseline: z_exit = 0.5, H = 10 trading days. The adverse boundary is direction-specific: for d=+1, failure occurs if z reaches or exceeds +3.0 before convergence; for d=-1, failure occurs if z reaches or falls below -3.0. If neither condition occurs by H, label failure/timeout according to the project target definition.

| Field | Value stored at event time |
| --- | --- |
| event_id | Unique immutable event key. |
| pair_id | Pair registry key. |
| event_date | End-of-day signal date. |
| snapshot_id | Latest effective monthly econometric snapshot. |
| z_entry | Observed z-score at trigger. |
| direction | +1 or -1. |
| alpha / beta | Frozen relationship coefficients. |
| coint_tstat / pvalue | Relationship validity diagnostics known at event time. |
| half_life / beta_drift / correlations | Frozen or trailing diagnostics known at event time. |
| label fields | Written only by the later label-construction job; never available to feature generation. |

# 14. Outputs passed to ML and the UI

## 14.1 Relationship-quality ML features

| Feature | Type | Point-in-time meaning |
| --- | --- | --- |
| coint_tstat | continuous | Strength of current Engle-Granger rejection. |
| coint_pvalue | continuous | Cointegration test p-value. |
| beta | continuous | Current long-run relative coefficient. |
| beta_drift_pct | continuous | Change in coefficient from prior monthly snapshot. |
| half_life_days | continuous / nullable | AR(1) mean-reversion speed. |
| corr_20d / corr_60d | continuous | Recent return co-movement. |
| spread_vol_20d_ratio | continuous | Recent spread volatility relative to formation scale. |
| zero_crossings_252d | integer | Recent equilibrium-crossing frequency. |
| days_since_zero_cross | integer | Recency of last crossing. |
| relationship_age_months | integer | Number of consecutive valid monthly snapshots. |
| integration_warning | categorical/binary | Ambiguous I(1) diagnostics. |
| cusum_warning | binary optional | Secondary parameter-stability warning. |

## 14.2 Spread-state ML features

| Feature | Definition |
| --- | --- |
| z_score | Current standardised divergence. |
| abs_z | Magnitude of divergence. |
| spread_velocity_1d | One-day change in raw spread. |
| z_velocity_1d | One-day change in z-score. |
| distance_to_exit | abs_z - z_exit. |
| distance_to_adverse | z_stop - abs_z in the event direction. |
| prior_crossing_count | Number of previous qualifying divergence events for the pair in a trailing window, computed only from past data. |

What is not passed from this engine The engine does not create market-context features such as VIX, market/sector returns, abnormal volume, days-to-earnings, news sentiment, event materiality, or agent conclusions. Those are constructed by other layers and joined by event_id / event timestamp.

# 15. Exact implementation function map and tech stack

## 15.1 Python stack

| Component | Library / function | Purpose |
| --- | --- | --- |
| Tabular/time alignment | pandas | Date-index joins, rolling windows, group operations. |
| Numeric transforms | numpy | log, differencing, vectorised calculations. |
| Long-run OLS | statsmodels.api.OLS + statsmodels.tools.add_constant | Estimate α and β and retain residuals. |
| Engle-Granger test | statsmodels.tsa.stattools.coint | Primary no-cointegration test with MacKinnon p-value. |
| ADF diagnostics | statsmodels.tsa.stattools.adfuller | Integration-order diagnostics on price levels/differences. |
| KPSS diagnostics | statsmodels.tsa.stattools.kpss | Stationarity-null cross-check. |
| Optional CUSUM | statsmodels.stats.diagnostic.breaks_cusumolsresid | Secondary parameter-stability diagnostic. |
| Persistence | duckdb + parquet | Store monthly snapshots, daily states, events and audit lineage. |

## 15.2 Application-level function responsibilities

| Function | Inputs | Returns |
| --- | --- | --- |
| load_pair_window | pair_id, estimation_date, snapshot_id | Aligned 504-day A/B adjusted-price frame. |
| transform_pair_prices | aligned price frame | y, x, Δy, Δx and validation flags. |
| test_integration_order | y, x | ADF/KPSS result object and compatibility flags. |
| fit_cointegrating_regression | y, x | α, β, residual vector, OLS diagnostics. |
| run_engle_granger | y, x | coint t-stat, p-value, critical values, test settings. |
| estimate_half_life | formation spread | AR(1) ρ, φ, half-life and validity flag. |
| compute_stability_metrics | current/prior snapshots + price frame | correlations, beta drift, spread-vol ratio, crossings, optional CUSUM. |
| assign_pair_status | all tests + lifecycle history | ACTIVE/WATCH/RETIRED and reason codes. |
| build_daily_pair_state | snapshot + subsequent daily prices | spread, z-score, velocity fields per date. |
| detect_divergence_events | daily state + unresolved-event state | non-overlapping event records. |
| label_event | future z path, fixed horizon | success/failure/timeout and resolution metadata. |
| persist_relationship_snapshot | result object + lineage IDs | DuckDB monthly pair snapshot row(s). |

No hidden side effects Each function should be deterministic for a fixed data_snapshot_id and configuration version. Retrieval from external providers belongs to the data-ingestion layer, not inside econometric functions.

# 16. Persistent schemas and data lineage

## 16.1 Monthly relationship snapshot

| Field group | Required fields |
| --- | --- |
| Identity | pair_id, y_ticker, x_ticker, estimation_date, effective_start, effective_end, relationship_spec_version. |
| Window | window_start, window_end, n_obs, formation_window_days. |
| Integration | y_adf_level_p, y_adf_diff_p, x_adf_level_p, x_adf_diff_p, optional KPSS fields, integration_flag. |
| Engle-Granger | alpha, beta, coint_tstat, coint_pvalue, critical values, trend_spec, autolag_spec. |
| Spread scale | spread_mean, spread_std. |
| Mean reversion | ar1_rho, error_correction_phi, half_life_days, half_life_valid. |
| Stability | corr_20d, corr_60d, beta_drift_pct, spread_vol_20d, spread_vol_ratio, zero_crossings_252d, days_since_zero_cross, optional cusum_pvalue. |
| Lifecycle | pair_status, status_reason, consecutive_invalid_snapshots. |
| Lineage | data_snapshot_id, source_price_snapshot_ids, config_hash, created_at_utc. |

## 16.2 Daily pair state

| Field | Purpose |
| --- | --- |
| pair_id, trading_date, relationship_snapshot_id | Join keys. |
| alpha, beta | Frozen coefficients used that day. |
| spread, z_score, abs_z | Current relationship state. |
| spread_velocity_1d, z_velocity_1d | Short-run divergence dynamics. |
| pair_status | Eligibility inherited from snapshot. |
| data_available_at | Point-in-time availability boundary. |
| data_snapshot_id | Reproducibility. |

# 17. Leakage controls, validation, and failure handling

## 17.1 Non-negotiable temporal controls

- Formation-window observations must be on or before the estimation date.
- A monthly relationship snapshot becomes effective only after it is estimated; historical events cannot join to later snapshots.
- No future price is used in spread scaling, half-life estimation, or event features.
- Future z-scores are read only by the label-construction job after the event row is frozen.
- No threshold, pair orientation, formation-window length, or cointegration significance rule may be changed after reviewing final test results.

## 17.2 Numerical/data failure conditions

| Failure | Handling |
| --- | --- |
| Near-constant or invalid price series | Reject window; data-quality reason code. |
| Perfect/near-perfect collinearity | Store warning; statsmodels coint may return extreme statistic; review raw data for duplication. |
| spread_std <= epsilon | Reject snapshot; z-score undefined. |
| Insufficient common dates | No snapshot; pair WATCH/RETIRED depending persistence. |
| Missing current signal-day price | No daily state/event for that date; no forward fill. |
| Half-life invalid | Store null + flag; do not fabricate a value. |
| OLS / statistical test exception | Persist failed job record with pair/date/config; do not silently skip. |

## 17.3 Unit and integration tests for code

- Synthetic cointegrated series should be classified as cointegrated at a high rate under the fixed specification.
- Independent random walks should usually fail the cointegration gate.
- No feature row may contain dates later than its event timestamp.
- Re-running the same snapshot/configuration must reproduce identical α, β, z-scores, events, and labels.
- Changing the pair orientation must change the output in a documented way; production orientation remains fixed by registry.

# 18. Recommended baseline configuration and sensitivity grid

## 18.1 Locked starting configuration

| Parameter | Baseline value | Why |
| --- | --- | --- |
| Price input | log adjusted close | Corporate-action-consistent level relation. |
| Pair model | Engle-Granger, constant only | Simple, interpretable two-asset long-run relation. |
| Formation window | 504 trading days | ~2 years; balances stability and adaptation. |
| Re-estimation | Monthly, effective next session | Point-in-time and computationally manageable. |
| EG autolag | AIC | Standard automatic lag selection. |
| Cointegration alpha | 5% | Initial eligibility threshold. |
| Entry z | 2.0 | Meaningful statistical divergence. |
| Exit z | 0.5 | Defines successful convergence. |
| Adverse z | 3.0 in event direction | Failure boundary. |
| Label horizon | 10 trading days | Short-term statistical-arbitrage horizon. |
| WATCH rule | 1 failed monthly validity snapshot | Conservative suppression of new signals. |
| RETIRED rule | 2 consecutive invalid monthly snapshots or manual terminal reason | Removes persistently broken relationships. |
| CUSUM | Diagnostic only | Does not duplicate AI structural-break decision. |

## 18.2 Sensitivity analysis - validation only

| Dimension | Permitted validation grid |
| --- | --- |
| Formation window | 252 / 504 / 756 trading days. |
| Cointegration threshold | 1% / 5% / 10%. |
| Entry threshold | 1.5 / 2.0 / 2.5 standard deviations. |
| Exit threshold | 0.0 / 0.5 / 1.0 standard deviations. |
| Label horizon | 5 / 10 / 20 trading days. |
| Adverse boundary | 2.5 / 3.0 / 3.5 standard deviations. |
| Re-estimation cadence | Monthly baseline; weekly only as sensitivity if computation permits. |

Model-selection rule The final configuration is selected using only training and validation periods and then frozen. The final test period is opened once. Sensitivity results are reported transparently rather than used to cherry-pick the best historical outcome.

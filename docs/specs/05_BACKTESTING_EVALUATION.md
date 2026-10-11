# Backtesting & Evaluation Framework

> **Agent-use specification.** Canonical implementation decisions are in [`../DECISIONS.md`](../DECISIONS.md). This Markdown is the coding-agent source of truth for this subsystem. The PDF in `docs/archive/pdfs/` is archival/human-readable only.

# 1. Evaluation objectives and hypotheses

| **Comparison**           | **Question**                                                                                               |
|--------------------------|------------------------------------------------------------------------------------------------------------|
| Baseline 0 vs Baseline 1 | Does rolling econometric relationship validity improve threshold-based pair selection?                     |
| Baseline 1 vs Model A    | Does the calibrated quantitative model select divergence events with higher realised mean-reversion quality? |
| Model A vs Model B       | Do structured point-in-time event/NLP features improve ranking/calibration and downstream event selection? |
| Model B vs Full System   | Does source-grounded language AI reduce failed opportunities without vetoing too many successful ones?     |

## 1.1 Primary evidence types

- Predictive discrimination and probability calibration.
- Event-selection efficiency: success/failure composition across accepted/rejected events.
- Economic outcomes under one fixed simulator and cost assumptions.
- Agent-specific rejection, false-veto, evidence-validity, and abstention metrics.
- Robustness by time, pair, sector, market stress, event type, and implementation costs.

**No single headline metric**

A higher Sharpe alone is not sufficient. The report must show whether the predictive model is calibrated, whether risk improvement comes from rejecting failures rather than accidental concentration, and whether results survive reasonable cost and period slices.

# 2. Experimental freeze and chronological partitions

Research v2's calibrated logistic B-both versus matched A at the 20-session
horizon is the primary forecasting comparison. XGBoost, the structured-feature
ablations and the 10/30-session horizons remain predeclared comparisons. The
trading ladder below is a separate economic evaluation; it does not restrict
the broad v2 forecasting population to ACTIVE events.

| **Partition** | **Working dates**                      | **Allowed use**                                                                                                                  |
|---------------|----------------------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| Fitting       | 2006-2019 eligible events; source history starts in 2004 | Fit preprocessing and models after the 504-common-session formation warm-up. |
| Forward tuning | 2018/2019 folds within the fitting period | Select among the frozen, matched logistic/XGBoost tuning budgets. |
| Calibration   | 2020-2021 eligible events | Fit the frozen monotone Platt calibrator, without assessment outcomes. |
| Assessment    | 2022-2023 eligible events | Report the predeclared development comparisons; do not select a favorable model, horizon or subgroup. |
| Final test    | 2024-2025 eligible events | Outcomes/performance remain locked until method freeze and explicit user authorization. |
| Embargo       | Complete 20-session target window; 10/30 for the corresponding sensitivities | Purge every partition/fold boundary by the full target horizon, even when an event converges earlier. |

Phase 5's genuine historical pilot and Phase 6's economic assessment are pending.
Any further development policy choice must retain its actual timing and a new
version; the assessment period is not an unrestricted threshold-tuning set.

## 2.1 Freeze manifest

Before the final test is opened, write a machine-readable experiment manifest containing pair universe, label policy, feature schema, Model A/B artefacts, calibrator, probability thresholds, agent prompt/schema versions, decision policy, execution convention, cost assumptions, and code/data commit IDs.

- Changing any headline method after inspecting final-test results creates a new experiment and invalidates the previous “untouched test” claim.
- Point-in-time pair and trailing market features continue to refresh according to the pre-frozen rule during the final test; the predictive model and policy do not retrain.

# 3. Evaluation ladder and exact acceptance rules

| **Version**                   | **What changes**                                                                  | **Automated acceptance rule**                                                             |
|-------------------------------|-----------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| Baseline 0 - threshold only   | Trade every fresh divergence crossing in the curated pair universe.               | Fresh \|z\| crossing; ignores cointegration/lifecycle validity.                           |
| Baseline 1 - valid pairs only | Add econometric eligibility.                                                      | Fresh crossing AND pair ACTIVE at event time.                                             |
| Model A - ML filter           | Add calibrated quantitative-model selection; logistic is primary. | Baseline 1 event AND calibrated A P(revert) >= frozen ML threshold. |
| Model B - ML + event features | Add structured point-in-time SEC metadata/tone/catalyst features; logistic B-both is primary. | Baseline 1 event AND calibrated B P(revert) >= the matched frozen threshold. |
| Full system                   | Add point-in-time event intelligence, agents and deterministic controller.        | Only final status CANDIDATE enters simulated trade; REVIEW/NO TRADE/ABSTAIN are withheld. |

One change per rung

The primary Model B adds structured SEC features to calibrated logistic A.
The Full System then uses the underlying admissible evidence and structured
extraction in the agent/controller layer, so the incremental value of reasoning
can be measured separately from tabular event features. Keep the complete
predeclared model-family/feature-block comparisons; economic results must name
the stored model identities driving acceptance.

# 4. Raw signal universe versus ML event universe

Baseline 0 requires threshold crossings even when a pair is not currently cointegrated/ACTIVE. Therefore the backtester maintains a raw signal table distinct from the ML divergence-event table.

| **Object**               | **Eligibility**                                                                         | **Use**                                                                               |
|--------------------------|-----------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| raw_divergence_signals   | Any curated pair with an estimable current spread/z-score and fresh threshold crossing. | Baseline 0 candidate universe; stores relationship-validity fields even when invalid. |
| valid_divergence_signals | Raw signal where pair lifecycle=ACTIVE and required econometric rules pass.             | Baseline 1 universe.                                                                  |
| divergence_events        | Estimable fresh crossing with required ML features/label-policy metadata, irrespective of ACTIVE. | Broad matched v2 Model A/B forecasting and scoring population; UNKNOWN evidence remains explicit. |
| full_system_events       | Scored event with admissible evidence/agent/controller outputs.                         | Full-system evaluation subset; coverage/abstention explicitly reported.               |

## 4.1 Fair-comparison principle

When comparing two adjacent rungs, report results on both the natural eligible universe and a common matched subset where both versions have the required data. This prevents a layer from appearing better merely because missing data removed difficult observations.

Every proposed simulation retains an explicit disposition, including failed
execution. Unknown returns are excluded from return calculations with their
denominator and reason reported; they are never converted to zero or silently
dropped. A quota-limited Full-System schedule requires a separately frozen,
target-blind schedule and a matched B comparison, not a whole-cohort claim.

# 5. Simulated pair construction and position sizing

The project simulates a beta-weighted long/short pair using the hedge ratio frozen in the relationship snapshot at signal time. Only pairs with positive, economically sensible beta are eligible for the headline pair trade.

$$
w_{A,i}=-\frac{s_i}{1+|\hat\beta_i|},\qquad
w_{B,i}=\frac{s_i\hat\beta_i}{1+|\hat\beta_i|},\qquad
s_i=\operatorname{sign}(z_i).
$$

If z>0, leg A is rich relative to B: short A and long beta-weighted B. If z<0, the signs reverse. Absolute weights sum to approximately one for positive beta, so one event uses one unit of gross pair notional in the event-level return calculation.

For initial gross notional $G_i$, entry prices $P_{j,i}^{entry}$ and the above
signed notional weights, freeze share units
$q_{j,i}=G_iw_{j,i}/P_{j,i}^{entry}$. At any mark $u$, gross event return is

$$
R_{i,u}^{gross}=\frac{\sum_jq_{j,i}(P_{j,u}-P_{j,i}^{entry})}{G_i}.
$$

The weights size the entry only. Share units remain fixed until exit; do not
compound daily constant-weight pair returns or rebalance the legs each day.

**Frozen hedge ratio**

The entry hedge ratio is frozen for the life of the simulated event. Re-estimating beta after entry would change the position using information not available at the original decision and make comparisons harder to interpret.

The positive-beta rule is an execution eligibility gate, not a change to v2
forecast labels or the broad A/B cohort. Invalid execution snapshots are
reported as not entered rather than rewriting registry membership.

Monthly relationship parameters become usable at the exact next XNYS open
after their formation endpoint. The request's snapshot `available_at` is
that first-usability bound or later, and must be no later than the signal cutoff.
A same-close refit cannot drive the signal formed at that close.

# 6. Signal timing, entry, monitoring, and exit

| **Step**            | **Convention**                                                                                                          |
|---------------------|-------------------------------------------------------------------------------------------------------------------------|
| Signal              | Computed after market close on event day t0 using information through t0.                                               |
| Entry               | Next trading day open (t0+1) using adjusted/open-consistent price series; captures overnight gap after the signal.      |
| Monitoring          | At each subsequent close, compute z using the relationship parameters frozen for the signal period.                     |
| Convergence trigger | Close reaches \|z\| <= 0.5.                                                                                            |
| Adverse trigger     | Close reaches $s_i z \ge 3.0$, where signal sign $s_i$ is frozen; an opposite-side overshoot is neither convergence nor this stop. |
| Time stop           | Close of the 20th XNYS session after the signal if neither trigger occurs; separately versioned 10/30-session sensitivities. |
| Execution of exit   | Open of the exact next XNYS session after the close-based convergence/stop/timeout trigger. |
| Missing next open   | Use explicit missing-execution flag; do not silently substitute a future convenient price.                              |

Monitoring begins at the entry session's close. Success requires an observed
close in the convergence band; a jump from positive to negative z without a
band observation is not convergence. No later refit changes the frozen
alpha/beta/spread mean/standard deviation. Missing required monitoring prices,
truncated paths or declared lifecycle termination produce an explicit unknown
execution result; later statistical WATCH/RETIRED alone does not censor a path.

The fixture slice requires an explicit ordered XNYS session list and
open/close prices on a declared compatible adjustment basis. A later Yahoo
adapter must derive adjusted open as `raw_open * (adjusted_close / raw_close)`
from a single captured price generation, with the corresponding adjusted
close. This is a retrospective corporate-action adjustment assumption, not a
vintage feed. The current synthetic tests do not establish actual historical
adapter correctness or dividend/borrow executability.

## 6.1 Label versus realised trade

The supervised label is defined from the close-based z path. The economic backtest uses a realistic next-open execution convention. Therefore a y=1 event can still have a weak or negative simulated return because of entry/exit gaps and costs. This is desirable: predictive success and economic profitability are related but not identical.

# 7. Transaction costs, borrow costs, and implementation assumptions

$$
C_i=\frac{c_{entry}\sum_j|q_{j,i}|P_{j,i}^{entry}
 +c_{exit}\sum_j|q_{j,i}|P_{j,i}^{exit}}{G_i}
 +b_i|w_i^{short}|\frac{H_i}{252}.
$$

| **Cost component**          | **Synthetic scenario; production assumptions remain DRAFT** | **Predeclared sensitivity proposals; freeze before economic assessment** |
|-----------------------------|--------------------------------------------------|--------------------------------------------------------------------------------|
| Entry trading cost          | 5 bps of actual entry gross turnover | 2.5 / 5 / 10 / 20 bps. |
| Exit trading cost           | 5 bps of actual exit gross turnover | Same grid. |
| Short borrow                | 3% annualised on entry short notional, using exact open-to-open held XNYS sessions / 252 | 0% / 3% / 10% annualised. |
| Market impact               | Not separately modelled with daily public data   | Disclose as deployment limitation; high-cost sensitivity partially proxies it. |
| Hard borrow availability    | Not reliably available in public history         | Prototype flag/limitation; no claim of live executability.                     |
| Dividends/corporate actions | Adjusted price framework where possible          | Large corporate events manually checked in case studies.                       |

**Cost assumptions are not facts**

The baseline values are transparent scenario parameters, not claims about institutional execution. Headline results must include a cost sensitivity table.

The first Phase 6 implementation uses these numbers solely for deterministic
fixtures. The new production execution configuration leaves required cost and
adjustment assumptions unresolved and refuses execution while DRAFT. Freeze
the actual cost scenarios, borrow convention and adjustment policy in a new
experiment identity before a historical economic assessment. Preserve the
legacy `configs/backtest.yaml` reference contract.

# 8. Event-level return and path metrics

| **Metric**                         | **Definition / purpose**                                                                       |
|------------------------------------|------------------------------------------------------------------------------------------------|
| label_success                      | Whether the predefined mean-reversion target succeeded.                                        |
| gross_pair_return                  | Fixed-share mark-to-market P&L between exact entry/exit opens divided by entry gross notional. |
| net_pair_return                    | Gross pair return minus trading and borrow costs.                                              |
| holding_days                       | Exact XNYS open-to-open session intervals from entry through executed exit. |
| maximum adverse excursion (MAE)    | Minimum gross fixed-share return sampled at entry (zero), observed monitored closes and executed exit open. |
| maximum favourable excursion (MFE) | Maximum gross fixed-share return over the same discrete observations; intraday extrema are unavailable. |
| exit_reason                        | CONVERGENCE / ADVERSE_STOP / TIMEOUT / DATA_FAILURE.                                           |
| overnight_entry_gap                | Difference between signal close and next-open execution state; useful error-analysis variable. |

`label_success` belongs to the existing supervised target and must be joined
under its immutable label identity; it is not inferred from realized net
return. The fixture engine can explain its own close-based exit without reading
stored target files. For an entered but unpriced trade, final gross/net return,
final costs and full-path metrics remain null; partial observations are not a
completed economic outcome. Separately named `partial_mae`/`partial_mfe`
record the observed gross-return prefix for an UNPRICED position, including
entry zero; they cannot enter completed-event excursion statistics.

## 8.1 Selection metrics

- Accepted-event success rate and failure rate.
- Mean/median net return per accepted event.
- Distribution and lower-tail quantiles of net returns.
- Rejected-event counterfactual success/failure and return distribution, using the same simulator.
- Candidate retention rate: accepted / eligible events.

# 9. Portfolio-level simulation

Event-level analysis is primary because it measures selection quality directly. A secondary portfolio simulation converts accepted events into one daily strategy return series for Sharpe/drawdown reporting.

| **Rule**          | **Working specification**                                                                                                                                                                                                                |
|-------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Capital           | Normalised initial NAV = 1.0.                                                                                                                                                                                                            |
| Allocation        | Equal gross allocation across all open accepted pair trades on each day.                                                                                                                                                                 |
| Gross exposure    | Total gross exposure capped at 1.0 in the prototype; no leverage.                                                                                                                                                                        |
| Concurrent trades | All accepted trades may coexist subject to one open trade per pair; report number of simultaneous positions.                                                                                                                             |
| Reweighting       | Daily equalisation across open pairs is avoided to reduce artificial turnover; allocate equal notional at entry from available capital and release on exit. A simpler equal-open-position alternative may be used if frozen before test. |
| Cash              | Unused capital earns zero in the prototype; disclose.                                                                                                                                                                                    |
| Overlapping pairs | Allowed, but report concentration by ticker and sector; no hidden manual exclusions.                                                                                                                                                     |

## 9.1 Daily portfolio return

$$
r_t^{port}=\sum_{i\in O_t}a_{i,t}r_{i,t}^{pair}.
$$

Weights a_i,t are determined by the frozen portfolio rule, not optimised using final-test performance.

# 10. Predictive ML evaluation

| **Metric**        | **Why reported**                                                                     |
|-------------------|--------------------------------------------------------------------------------------|
| ROC-AUC           | Threshold-independent ranking quality.                                               |
| PR-AUC            | More informative when success/failure classes are imbalanced.                        |
| Precision         | Among events accepted by the frozen ML threshold, fraction that are label successes. |
| Recall            | Fraction of all label successes retained by the filter.                              |
| F1                | Single threshold-based precision/recall balance.                                     |
| Confusion matrix  | Transparent TP/FP/TN/FN counts at the frozen threshold.                              |
| Brier score       | Probability accuracy/calibration-sensitive score.                                    |
| Calibration curve | Predicted probability bins versus observed success frequency.                        |

$$
\mathrm{Brier}=\frac{1}{N}\sum_{i=1}^{N}(\hat p_i-y_i)^2.
$$

**Accuracy is not a headline metric**

A naive classifier can look good under imbalance. Ranking, calibration, and accepted-event precision/recall are more informative for this application.

# 11. Calibration and selection-efficiency evaluation

| **Analysis**                 | **Output**                                                                                                                             |
|------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| Reliability curve            | For probability bins, compare mean predicted P(revert) with observed success rate.                                                     |
| Probability buckets          | LOW / MEDIUM / HIGH bucket count, success rate, mean net return, failure rate.                                                         |
| Raw vs calibrated Brier      | Shows whether Platt calibration improves probability quality.                                                                          |
| Top-decile / high-score lift | Success rate in high-score subset relative to Baseline 1 event base rate.                                                              |
| Threshold curve              | Explicitly labelled development sensitivity under its recorded timing; the matched v2 0.65 reporting threshold remains unchanged. Final evaluation uses frozen policy. |

## 11.1 Selection efficiency

$$
\mathrm{Lift}(B)=\frac{P(y=1\mid \hat p\in B)}{P(y=1)}.
$$

A useful ML layer should rank events so that higher predicted-probability groups have higher realised success rates. Economic return is reported beside this but is not used to redefine the target after the fact.

# 12. Incremental value and ablation analysis

| **Increment**           | **Interpretation**                                                            |
|-------------------------|-------------------------------------------------------------------------------|
| Baseline 1 - Baseline 0 | Value of econometric relationship validity.                                   |
| Model A - Baseline 1    | Value of supervised quantitative event selection.                             |
| Model B - Model A       | Value of structured point-in-time event/NLP features.                         |
| Full System - Model B   | Value of point-in-time language intelligence + agent/controller risk control. |

## 12.1 Feature-family ablations

The authorized v2 comparison retains A, B-metadata, B-tone, B-catalyst and
B-both under both calibrated logistic and the matched-budget XGBoost family
for each of the 20/10/30-session horizons: thirty bundles overall. Logistic
B-both versus A at twenty sessions is primary. Economic acceptance must use
named frozen prediction identities rather than refitting inside a backtester.

The older quantitative-family proposals below are optional future experiments,
not additional frozen v2 bundles or implementation requirements for this slice.

| **Ablation**                       | **Question**                                                          |
|------------------------------------|-----------------------------------------------------------------------|
| Remove spread-state family         | Does the model need immediate divergence dynamics beyond entry z?     |
| Remove relationship-quality family | How much value comes from cointegration/stability diagnostics?        |
| Remove market-context family       | Does context improve prediction?                                      |
| Remove security-state family       | Are one-leg momentum/volume shocks informative?                       |
| Remove liquidity family            | Does implementation state help selection?                             |
| Remove event/NLP feature family    | How much value comes from structured point-in-time event information? |

**Preserve the declared comparison**

Do not use development assessment to choose a favorable family/horizon or
silently replace the v2 primary. Any new ablation needs its own recorded
timing/version before evaluation. Final results never authorize repeated
changes to the production feature set.

# 13. Agent/controller evaluation

$$
\mathrm{Failure\ Rejection\ Rate}=\frac{\#\{y=0\text{ events withheld}\}}{\#\{y=0\text{ Model B events}\}}.
$$

$$
\mathrm{False\ Veto\ Rate}=\frac{\#\{y=1\text{ events withheld}\}}{\#\{y=1\text{ Model B events}\}}.
$$

| **Metric**                        | **Definition / interpretation**                                                                        |
|-----------------------------------|--------------------------------------------------------------------------------------------------------|
| Failed-opportunity rejection rate | Share of Model B failures converted to REVIEW/NO TRADE/ABSTAIN by the full system.                     |
| False-veto rate                   | Share of Model B successes withheld by the full system.                                                |
| Candidate retention               | Share of Model B eligible events that remain CANDIDATE.                                                |
| Net failure reduction             | Change in number/rate of failed simulated trades after agent/controller gate.                          |
| Tail-loss reduction               | Change in worst/lower-tail event returns and drawdown contribution.                                    |
| Abstention rate                   | Share withheld because the system cannot make a defensible classification.                             |
| Reason-code distribution          | Why opportunities were withheld: high break risk, data failure, low score, market-stress warning, etc. |

## 13.1 Interpretation trade-off

A system that rejects every event has perfect failure rejection but zero usefulness. Agent evaluation must therefore report failure rejection and false-veto/retention together.

# 14. Human-labelled NLP evaluation subset

The agent layer requires direct evaluation of its evidence-processing quality, not only downstream returns. Build a stratified human-labelled subset from historical events before inspecting full-system test outcomes.

| **Label field**          | **Human annotation**                                             |
|--------------------------|------------------------------------------------------------------|
| event_type               | Dominant material event category or NONE/UNKNOWN.                |
| affected_leg             | A / B / BOTH / UNKNOWN.                                          |
| direction                | Positive / negative / mixed / neutral / unknown.                 |
| materiality              | LOW / MEDIUM / HIGH / UNKNOWN.                                   |
| relationship_relevance   | LOW / MEDIUM / HIGH / UNKNOWN.                                   |
| evidence validity        | Whether the cited chunk genuinely supports the extracted claim.  |
| source completeness note | Whether available SEC evidence appears sufficient for the label. |

- Minimum 50 events; aim for about 100 if group capacity permits.
- Stratify across sectors, years, successful/failed events, and events with/without recent 8-Ks.
- Report per-field accuracy and macro-F1 for categorical fields where class counts support it.
- Report evidence-validity rate separately from event-classification accuracy.

# 15. Robustness slices and stress assumptions

| **Slice / sensitivity**   | **Required report**                                                                                                     |
|---------------------------|-------------------------------------------------------------------------------------------------------------------------|
| By calendar year          | Event count, success rate, mean net return, ML metrics where sample supports.                                           |
| By sector                 | Same metrics; flag very small samples.                                                                                  |
| By pair                   | Distribution of contribution; identify concentration in a few pairs.                                                    |
| By divergence sign        | Positive versus negative z events.                                                                                      |
| By market stress          | Observable VIX / realised-volatility buckets defined before final-test evaluation.                                      |
| By event type/materiality | Full-system subset where labels exist.                                                                                  |
| Transaction cost          | 2.5 / 5 / 10 / 20 bps per side.                                                                                         |
| Borrow cost               | 0% / 3% / 10% annualised short notional.                                                                                |
| Threshold sensitivity     | Explicit development sensitivity with recorded timing; preserve canonical v2 0.65 coverage and report later frozen trading policy plus predeclared sensitivities. |
| Label sensitivity         | Optional pre-specified alternative horizon/exit definitions reported separately; do not choose best after test.         |

# 16. Statistical uncertainty and dependence

Divergence events are not perfectly independent: multiple pairs can trigger in the same market shock and the same pair can generate events over time. Standard iid confidence intervals can therefore be overconfident.

| **Method**                        | **Use**                                                                                                                                                             |
|-----------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Descriptive counts/distributions  | Always report N; avoid interpreting tiny slices as stable.                                                                                                          |
| Paired calendar-quarter forecast bootstrap | Canonical v2 predictive B-minus-A losses use 2,000 seeded paired quarter-block resamples; 2022-2023 has only eight blocks. Preserve these existing predictive reports. |
| Calendar-month economic bootstrap proposal | The original economic specification proposes month-block resampling for event success, returns and performance differences. This separate economic policy is not implemented or frozen by the fixture slice; freeze its estimands, pairing, block rule and sample limitations before historical economic assessment. |
| Pair-cluster sensitivity          | Recompute headline event metrics after leaving one pair out or one sector out.                                                                                      |
| No p-value fishing                | Do not run dozens of significance tests and select only favourable ones.                                                                                            |

**Uncertainty is secondary to design integrity**

The most important protection against false discovery is the frozen chronological test and transparent ablation ladder. Bootstrap intervals quantify uncertainty; they do not repair look-ahead or test-set tuning.

# 17. Error analysis and structural-break case studies

| **Case type**           | **What to inspect**                                                                         |
|-------------------------|---------------------------------------------------------------------------------------------|
| ML false positive       | High P(revert) but y=0: feature state, SHAP, market state, catalyst evidence, adverse path. |
| ML false negative       | Low score but y=1: whether model misses a recurring pattern or feature family.              |
| Correct agent veto      | Model B would trade a failure; full system withholds due to validated break evidence.       |
| False agent veto        | Model B success withheld; inspect event interpretation and policy threshold.                |
| Agent abstention        | Was missing evidence genuinely unavoidable, or is retrieval too weak?                       |
| Catastrophic tail event | Trace from raw source -> pair snapshot -> ML -> agents -> controller -> simulated P&L. |

## 17.1 Demo case selection

Choose demo cases after the final evaluation framework is frozen, not by cherry-picking only spectacular wins. Include at least one successful candidate, one correct structural-break rejection, one false veto/review, and one abstention/data-quality case if available.

# 18. Leakage, multiple testing, and research-governance controls

| **Risk**                     | **Control**                                                                                                         |
|------------------------------|---------------------------------------------------------------------------------------------------------------------|
| Look-ahead prices            | Signal at close t, execute at next open; rolling features end at t; labels alone use future.                        |
| Future pair parameters       | Use snapshot admissible at signal date; never full-sample beta/mean/std.                                            |
| Future market-state features | Use observable trailing market/VIX/volatility features only.                                                        |
| Future text                  | SEC acceptance/news publication timestamp <= event cutoff.                                                         |
| Test tuning                  | Freeze features, model, calibration, thresholds, agent policy and costs before final test.                          |
| Pair/data snooping           | Curated economic universe; document selection criteria; do not search thousands of pairs until backtest looks good. |
| Repeated variants            | Log every experiment; distinguish pre-specified headline from exploratory sensitivity.                              |
| Missing data selection       | Report coverage/matched-subset results; do not silently drop difficult full-system events.                          |

**Reproducible experiment ID**

Every evaluation output should be keyed by experiment_id containing data snapshot, pair/label policy, model A/B versions, agent/policy versions, execution-cost configuration, and code commit.

# 19. Strategy Lab UI specification

| **UI panel**           | **Content**                                                                                                       |
|------------------------|-------------------------------------------------------------------------------------------------------------------|
| Evaluation ladder      | Side-by-side table of B0, B1, Model A, Model B, Full System event counts and key outcomes.                        |
| Equity curves          | Net portfolio curves under identical cost convention; clearly label gross/net and variant.                        |
| Predictive diagnostics | ROC/PR, calibration curve, Brier, probability-bucket success rates.                                               |
| Selection funnel       | Raw signals -> valid pairs -> ML accepted -> Model B accepted -> final CANDIDATE, with reasons for rejection. |
| Agent impact           | Failure rejection, false-veto, abstention, break-risk buckets, rejected-trade counterfactual returns.             |
| Robustness controls    | Sector/year/market-stress filters; cost/borrow scenario selector.                                                 |
| Trade/event table      | Sortable event-level entry/exit, status, P(revert), break risk, return, exit reason and links to Pair Detail.     |
| Experiment manifest    | Frozen dates, thresholds, model/policy versions, cost assumptions, data snapshot.                                 |

## 19.1 Visual honesty

- Never default to a cherry-picked sector/year filter.
- Show event counts next to performance metrics.
- Do not hide variants with fewer/missing agent-coverage events; show coverage.
- Separate validation sensitivity charts from final-test headline results.

# 20. Storage schemas, functions, and artefacts

## 20.1 DuckDB tables

| **Object**                       | **Grain**                           | **Key fields**                                                                                    |
|----------------------------------|-------------------------------------|---------------------------------------------------------------------------------------------------|
| analytics.raw_divergence_signals | pair x fresh crossing               | signal_id, pair_id, date, z, relationship validity, snapshot_id                                   |
| analytics.backtest_trades        | experiment x accepted signal        | trade_id, variant, event/signal_id, entry/exit times/prices, weights, costs, returns, exit reason |
| analytics.backtest_daily         | experiment x variant x day          | date, variant, NAV, daily return, gross exposure, open count, turnover                            |
| analytics.evaluation_metrics     | experiment x variant x metric/slice | metric_name, value, N, slice keys, confidence interval if used                                    |
| analytics.agent_eval             | event/subset                        | human labels, extraction scores, evidence validity, veto outcome                                  |
| ops.experiments                  | one experiment                      | experiment_id, manifest path, code/data/model/policy versions, status                             |

## 20.2 Core functions

| **Function**                               | **Responsibility**                                           |
|--------------------------------------------|--------------------------------------------------------------|
| generate_raw_signals(...)                  | Fresh threshold crossings for Baseline 0 universe.           |
| accept_signal(variant, state)              | Apply B0/B1/Model A/Model B/full-system acceptance rule.     |
| simulate_pair_trade(signal, execution_cfg) | Next-open entry/exit, frozen weights, costs, path metrics.   |
| build_portfolio(trades, portfolio_cfg)     | Daily NAV/exposure/turnover series.                          |
| compute_predictive_metrics(...)            | AUC/PR/threshold/calibration statistics.                     |
| compute_agent_metrics(...)                 | Failure rejection, false veto, abstention, evidence metrics. |
| run_robustness_slices(...)                 | Sector/year/market-stress/cost/leave-one-out tables.         |
| run_experiment(manifest)                   | End-to-end frozen evaluation and artefact persistence.       |

# 21. Reporting tables and figures

| **Required output**              | **Minimum content**                                                                                                         |
|----------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| Table 1 - coverage/funnel        | Raw signals, valid signals, ML-complete events, Model A accepted, Model B accepted, full CANDIDATE/REVIEW/NO TRADE/ABSTAIN. |
| Table 2 - predictive performance | Logistic, Model A, Model B: ROC-AUC, PR-AUC, Brier, precision, recall, F1, N.                                               |
| Table 3 - event economics        | Variant: accepted N, success rate, mean/median gross/net return, MAE, holding days.                                         |
| Table 4 - portfolio performance  | Variant: cumulative/annualised return, annualised volatility, Sharpe, max drawdown, turnover, concurrent positions.         |
| Table 5 - agent impact           | Failure rejection, false veto, retention, abstention, evidence validity.                                                    |
| Table 6 - robustness             | Key metrics across year/sector/market-stress and cost scenarios.                                                            |
| Figure 1                         | Evaluation funnel.                                                                                                          |
| Figure 2                         | Calibration curve / probability-bucket success.                                                                             |
| Figure 3                         | Net equity curves.                                                                                                          |
| Figure 4                         | Drawdown curves.                                                                                                            |
| Figure 5                         | Rejected versus accepted event-return distributions.                                                                        |
| Figure 6                         | Agent break-risk / decision confusion-style analysis.                                                                       |

# 22. Build sequence and acceptance criteria

| **Order** | **Deliverable**         | **Acceptance condition**                                                              |
|-----------|-------------------------|---------------------------------------------------------------------------------------|
| 1         | Raw signal generator    | B0 signal history reproducible independently of pair ACTIVE status.                   |
| 2         | Pair trade simulator    | Synthetic fixtures verify frozen share direction/size, exact next-open timing, close-based exits, gaps, costs and explicit unknown execution. |
| 3         | B0/B1 backtests         | Same simulator; only econometric eligibility differs.                                 |
| 4         | Model A/B evaluation    | Stored frozen predictions drive acceptance; no model fitting inside backtester.       |
| 5         | Full-system integration | Stored decisions drive trade acceptance; REVIEW/NO TRADE/ABSTAIN withheld.            |
| 6         | Metrics + portfolio     | Event and daily portfolio outputs reconcile to trade records.                         |
| 7         | Agent/human metrics     | Labelled subset and veto metrics reproducible.                                        |
| 8         | Robustness/bootstrap    | Pre-specified sensitivity tables generated from one experiment manifest.              |
| 9         | Strategy Lab            | UI reads stored experiment outputs rather than recomputing ad hoc.                    |
| 10        | Final freeze/run        | Final test opened once; report artefacts saved immutably.                             |

- All variants use the same execution and cost engine.
- No final-test threshold/hyperparameter/prompt/policy tuning.
- Every performance number traces to event/trade rows and experiment manifest.
- Coverage and sample counts accompany every metric.
- Headline conclusions distinguish predictive, risk-control, and simulated economic evidence.

# Appendix A. Execution defaults and unresolved production assumptions

These are fixture scenario values and predeclared proposals. They are not
accepted historical execution assumptions. Production remains DRAFT until its
required costs/adjustment policy and immutable experiment identity are frozen.

| **Parameter**                        | **Default**                                                                    |
|--------------------------------------|--------------------------------------------------------------------------------|
| Signal frequency                     | Daily close                                                                    |
| Entry threshold                      | fresh \|z\| >= 2.0                                                            |
| Convergence trigger                  | \|z\| <= 0.5                                                                  |
| Adverse stop                         | same-side \|z\| >= 3.0                                                        |
| Maximum horizon                      | 20 XNYS sessions primary; separate 10/30 sensitivities |
| Execution                            | Signal after close; enter next open; close-triggered exit next open            |
| Position weights                     | Beta-weighted entry notional, gross normalised to 1; fixed entry share units until exit |
| Entry cost                           | Fixture 5 bps of entry gross turnover; production unresolved |
| Exit cost                            | Fixture 5 bps of actual exit gross turnover; production unresolved |
| Borrow                               | Fixture 3% annualised entry short notional × open-to-open sessions / 252; production unresolved |
| Portfolio leverage                   | None; total gross <=1.0                                                       |
| Full-system auto-trade status        | CANDIDATE only                                                                 |
| Model A/B candidate threshold        | Preserve matched v2 0.65 reporting threshold; actual trading policy must be explicitly versioned |
| Review band                          | Defined by the separate versioned Phase 5 controller; fixture 0.45-0.65 is not a production freeze |
| Final test                           | 2024-2025                                                                      |
| Risk-free return in prototype Sharpe | 0 unless a separately versioned risk-free series is added; disclose explicitly |

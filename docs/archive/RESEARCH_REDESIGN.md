> **Historical proposal.** The accepted design is [the frozen v2 protocol](../RESEARCH_PROTOCOL.md); planning ranges and proposed alternatives below are not active methodology.

# Research redesign proposal after Phase 4

**Status: implementation authorized on 2026-10-06 in a separate research version.**
**Date: 2026-10-04.**  
**Scope: predictive usefulness and sample adequacy, using development data only.**

The strongest next step is a much broader, economically defined equity-pair
sample and longer history, followed by simpler models and a clearer separation
of calibration from evaluation. More LLM reasoning on the existing seven
validation observations cannot establish predictive usefulness. The existing
28-pair experiment remains an immutable reference, and 2024–2025 outcomes remain
locked under [DECISIONS.md](../DECISIONS.md).

The concrete predeclared implementation is [RESEARCH_V2_PROTOCOL.md](../RESEARCH_PROTOCOL.md).
The historical proposal and scarcity audit below remain the motivation, not a
claim that the expanded experiment has passed acceptance or improved prediction.

## What causes the small sample

The audit binds the frozen relationship generation
`relationships_f2f4c804ec0388ecce9fc6fd` and event generation
`events_6451711be4cb02d63a38d13b`. Queries explicitly restrict observation dates to
2016–2023; no final-test outcomes were read. The generated local audit is
`.acceptance/p4_scarcity_report.json`; the published Phase 3 acceptance report and
[STATUS.md](IMPLEMENTATION_HISTORY.md) provide the corresponding model and label counts.

| Development funnel | 2016–2023 | Validation 2022–2023 |
| --- | ---: | ---: |
| Monthly pair fits | 2,688 | 672 |
| Fits rejecting the no-cointegration null at 5% | 210 | 30 |
| Fits also passing the declared I(1) checks / ACTIVE | 184 | 17 |
| Raw fresh divergence crossings, irrespective of status | 1,111 | 274 |
| ACTIVE divergence crossings | 93 | 11 |
| Non-overlapping ACTIVE episodes | 68 | 7 |
| Supervised eligible episodes | 67 | 7 |
| Successful episodes | 9 | 0 |

All 2,688 development fits were estimable, with no hard data failures. The main
bottleneck is the relationship gate: only 17 of 672 validation pair-months are
ACTIVE, approximately 2.5%. Episode deduplication then reduces 11 eligible
crossings to seven observations. Removing that deduplication would mostly add
dependent observations from the same divergence, rather than new opportunities.

| Year | Eligible episodes | Successes |
| --- | ---: | ---: |
| 2016 | 15 | 1 |
| 2017 | 1 | 0 |
| 2018 | 5 | 0 |
| 2019 | 3 | 0 |
| 2020 | 21 | 8 |
| 2021 | 15 | 0 |
| 2022 | 3 | 0 |
| 2023 | 4 | 0 |

Eight of nine successes occur in 2020. This concentration makes both sample size
and regime coverage material. Seven observations with no positives cannot
identify ROC AUC, positive-class recall, or a useful probability-calibration
slope. They do not establish that the true success probability is zero.
Scikit-learn likewise identifies calibration without positive-class observations
as ineffective. [Probability calibration documentation](https://scikit-learn.org/stable/modules/calibration.html)

## Recommended main experiment

Create a separate `research-v2` configuration, source freeze and artifact lineage.
Begin with **250–500 domestic issuers and 500–1,000 economically plausible
candidate pairs**, and seek price/document history from **2004 onward**. These
are collection-planning ranges, not an assertion that all issuers have complete
history or that every pair should qualify. With the existing 504-session formation
window, complete 2004–2005 history would permit events from approximately 2006.

Candidate membership must follow documented business/industry criteria and dated
listing/identity rules. Freeze a reviewed list, or a reproducible formation-only
selection algorithm, before computing the added labels. Fix each new orientation
with one declared identifier-order rule; retain the original orientations exactly.
Do not select pairs by their realised reversion success, validation score, or
future performance. Record exclusions and missing source coverage explicitly.

A point-in-time security universe with inactive/delisted issuers is preferable to
backfilling today's index constituents. If an institutional entitlement is
available, assess CRSP coverage and permanent identifiers before expanding the
public-data prototype. Its documented stock database includes active/inactive
securities and identifiers intended to preserve historical security continuity.
Any source migration needs a new audited price/return contract, rather than a
silent substitution. [Official CRSP product description](https://indexes.morningstar.com/research-data-products/crsp-us-stock-databases)

At the current validation rate, seven episodes from 28 pairs equates to about
0.25 episodes per pair over two years. Simple scaling would suggest approximately
200 episodes from 800 comparable pairs. **This is only a workload estimate:**
shared issuers, changing regimes, selection rules and source gaps can materially
change that rate. More candidate pairs also introduce more statistical tests;
predeclare the multiplicity treatment and disclose all attempted pairs. A large
candidate count is not a large count of independent trades.

The planning objective is several hundred evaluation episodes, with successes
distributed across issuers and periods. A range such as 200–500 episodes and
30–50 successes is useful for budgeting, but is **not a label-based inclusion
rule or a universal adequacy threshold**. Size the actual model to the observed
development sample and desired metric precision. Binary-model sample adequacy
depends on outcome frequency, complexity, expected signal and estimation
precision; a single events-per-variable rule is insufficient. This principle is
an application of general prediction-model methodology, not a finance-specific
sample-size guarantee. [Riley et al., original sample-size method](https://pmc.ncbi.nlm.nih.gov/articles/PMC6519266/)

Broader history is also consistent with the scale of established pairs-trading
research: the original Gatev–Goetzmann–Rouwenhorst study evaluated daily data over
1962–1997. Its strategy and historical results do not validate this project's
cointegration gates, ML labels or present-day profitability. [Original NBER study](https://www.nber.org/papers/w7032)

## Label horizon: a separate sensitivity study

Keep the current 10-session target as the reference. Development episodes have
median estimated half-life **10.99 sessions**; 39 of 68 exceed ten sessions.
Across ACTIVE monthly fits, the median is **12.57 sessions**, and 133 of 184 exceed
ten. Training failures comprise 17 adverse stops and 34 timeouts; validation
failures comprise two stops and five timeouts. One further training episode is
excluded by the partition embargo.

Under an idealised exponential-decay approximation, a spread moving from
|z| = 2 to |z| = 0.5 needs roughly two half-lives. That approximation motivates
examining the economic meaning of the horizon; it does not predict an individual
event's outcome. Monthly-fit uncertainty, changing equilibrium and adverse stops
remain relevant.

Predeclare a small sensitivity set of **10, 20 and 30 sessions**, preserving the
entry, success and adverse boundaries and entry-frozen coefficients. Give each
horizon its own label version, episode registry and full-window embargo. Longer
episodes can reduce event counts and increase exposure, borrow costs and adverse
outcomes, so compare success rate, counts and later economic results together.
Do not lengthen the horizon repeatedly until positives appear or silently replace
the primary target with whichever looks best. Selecting a new primary horizon is
a recorded methodology decision before the final run.

## Modelling and evaluation changes worth testing

For `research-v2`, begin with a training-prevalence probability baseline and a
strongly regularised logistic model using a small, prespecified feature subset.
Compare the existing XGBoost model afterward. Nine training successes do not
support confident inference from dozens of quantitative/event features, deep
trees and repeated hyperparameter searches. Additional complexity must earn its
place through chronological predictions, rather than training fit.

Use expanding forward folds for parameter selection and preserve each full
label-window embargo. Reserve a declared tail of development history for
calibration—one concrete proposal is classifier fitting/tuning through 2019,
calibration during 2020–2021, and assessment during 2022–2023. Freeze those dates
before examining added labels, apply them identically to Models A and B, and
report the calibration cohort's regime composition. This is a new protocol;
the reference model continues to use its original dates. The already inspected
28-pair validation outcomes do not become untouched observations again simply
because a new protocol is created.

Threshold selection must use development/calibration information and a declared
criterion. Keep the reference threshold 0.65 for the existing experiment, and
report selection coverage and uncertainty alongside precision. Raw-score
assessment and calibration-fit metrics must remain distinct. Missing one-class
folds remain explicit; do not fabricate a class balance.

Report both event-weighted and pair/issuer-balanced results, yearly/sector
coverage, and issuer/date dependence. Use time blocks and issuer-connected
clusters for uncertainty estimates and include a prespecified sensitivity to
the block construction. Multiple pairs sharing one issuer and simultaneous
sector shocks cannot be treated as independent evidence. Test robustness across
periods and with the 2020 regime reported separately, without choosing the best
regime as the headline result.

For Model B, retain every quantitative event, including evidence/extraction
UNKNOWNs, and compare on exactly the Model A observation registry. Schedule SEC
retrieval and extraction by dates/identities, not labels. Report coverage by year,
pair and partition; a free-tier extraction pilot with many unprocessed training
events is an engineering demonstration rather than a complete predictive test.
Audit a source-grounded extraction subset before investing in a larger LLM batch.

## A useful alternative if ACTIVE opportunities remain rare

Build a **separate diagnostic experiment** on deduplicated Baseline 0 episodes
from all estimable relationships. Validation currently has 274 raw Baseline 0
crossings before deduplication, versus eleven ACTIVE crossings. A broader
prediction population could support analysis of when mean reversion occurs,
with relationship diagnostics available as predictors or fixed downstream gates.

This changes the observation population and the meaning of the model comparison.
It must use a separate schema/protocol, preserve the ACTIVE-only reference ladder,
and show both broad-pool forecasting and ACTIVE-subset results. It does not
automatically create more admissible trades or demonstrate that abandoning the
relationship gate improves simulated returns.

## Execution order and freeze conditions

1. Preserve the completed phase artifacts and write the proposed source,
   membership/orientation, label, split and metric rules into a new protocol.
2. Establish source entitlements and dated identity/lifecycle coverage. Expand
   prices and SEC metadata first; estimate computational/document workload from
   outcome-blind formation and event counts.
3. Build the larger development registry and a complete sample-funnel report.
   Stop short of predictive claims if successes, regime coverage or metric
   precision remain inadequate; publish the observed shortfall.
4. Run the reference target and the prespecified horizon sensitivity, then matched
   simple/Model A/Model B development comparisons. Cache and manually audit SEC
   extractions; do not spend the full document/LLM budget before this diagnosis.
5. Freeze the chosen primary protocol, universe, transforms, calibration,
   thresholds, evidence policy, prompts, execution/cost rules and code/data hashes.
   Only explicit user authorisation may open headline 2024–2025 outcomes.

Oversampling or SMOTE can never increase validation information; duplicated
episodes do not create independent observations. Forcing successes by selecting
favourable companies, changing targets after looking at outcomes, or borrowing
2024–2025 results would answer a different and biased question. This proposal
improves the chance of a measurable study; it does not promise predictive alpha.

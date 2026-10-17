# P6 model and trading improvements: pre-registered plan

Status: **PRE-REGISTERED 2026-10-17** (DECISIONS section 43). This plan was written
and committed before any variant below was evaluated on 2022–2023. Every choice
is made with fit (2006–2019) and calibration (2020–2021) data only. Each
pre-registered variant is evaluated once on 2022–2023, and all of them are
reported.

## Integrity rules

1. **Timing.** These choices follow the observed v2 assessment and the P6
   development results (DECISIONS 42). The 2022–2023 results of this plan are
   **post-hoc exploratory** and are never described as confirmatory. The
   2024–2025 final test stays locked. Only it can show whether an improvement
   generalizes, and it may be used once, after an explicit owner unlock.
2. **Goal.** The goal is to give B the best *fair* chance, not to make B win.
   A and B always share rows, targets, folds, purging, tuning budget,
   calibration, trading rules, exits and costs. B differs only by its extra
   information. The result is reported whichever model leads.
3. **No re-selection.** No variant, threshold, family or feature set is
   chosen, dropped or reordered after viewing 2022–2023. Every later change is
   a new, separately labelled version.
4. **Denominators are kept.** UNKNOWN evidence and unknown executions stay
   explicit, and missing returns are never treated as zero.
5. **Scope.** h20 only, because of time. The h10/h30 horizons and the Full
   System are not part of this plan.

## Facts that motivate the plan (pre-assessment data or v2 design only)

- **B's information.** B adds 63 columns. FinBERT tone (18 columns) is known
  for both legs on 96–99 % of events. SEC filing metadata (14 columns) is
  unknown on only 12–17 %. The Gemma catalyst block is 31 columns, including 26
  near-constant one-hots, because extraction evidence exists for only about
  1.3 % of events (the frozen 500-event schedule).
- **Regularization.** v2 chose C = 0.01 for logistic B against C = 0.1 for A.
  A plausible reason is that heavy regularization dilutes the dense tone and
  filing signal along with the near-constant catalyst columns.
- **Label versus trade.** The supervised label is a close-based reversion
  event. The traded outcome depends on next-open fills, timeouts, stops and
  costs. A good label classifier is not necessarily a good trade selector.
- **Fixed threshold.** Calibrated probabilities are low (base rate 7–12 %), so
  a fixed probability threshold selects almost nothing.

## Data foundation (D)

Every h20 fresh episode event from 2006 to 2023 (about 29k) is simulated once
by the frozen shared engine, using the same bindings as the accepted P6
experiment. For each event the run records net return, status, exit reason,
holding period and the signal-time rung inputs. It uses the frozen Decision 36
headline policy, plus the exit variants of improvement 5. Exit variants are
evaluated only for events with signals in 2006–2021.

## Improvement 5: exit rule (decided first, shared by every rung)

The exit rule is decided first because it defines the trading outcome.

- **Variants (8):** an adverse stop at |z| ∈ {3.0 (frozen), 3.5, 4.0, none}
  crossed with a take-profit at |z| ≤ 0.5 (frozen) or mean crossing (z through
  0). The horizon stays at 20 sessions, matching the label. Entry, costs,
  borrow and eligibility are unchanged.
- **Selection.** Choose the highest mean net return per COMPLETE trade on
  Baseline 0 fit events (2006–2019) at headline costs.
- **Guard.** Keep the frozen rule unless the chosen variant also beats it on
  calibration events (2020–2021).
- **Status.** These are research-only variants. The frozen production policy
  object is unchanged, and the variants are never labelled frozen production.

## Improvement 2: predict what we trade

- **Economic target.** `y_econ` = 1 if a COMPLETE trade under the chosen exit
  has positive net return. NOT_ENTERED and UNPRICED events are excluded from
  training (unknown, not zero) but kept in every evaluation denominator.
- **Both targets.** Both the v2 reversion label and `y_econ` are modelled with
  the same machinery. Primary: `y_econ`. The reversion-target models are a
  pre-registered secondary.

## Improvement 4: features and model (matched budgets)

**Feature sets:**

- **A:** v2's 36 quantitative columns.
- **B_both:** v2's 99 columns, as before.
- **B_lean (70 columns):** A plus tone (18), SEC metadata (14),
  `evidence_available` and `one_sided_event`. This drops the 26 near-constant
  catalyst one-hots plus `source_count`, `document_recency_days` and
  `extraction_confidence`, which are undefined outside the schedule.
- **B_plus:** B_lean plus six pre-specified interactions between the diverging
  leg's information and the divergence:
  - `abs_z × sentiment_net_asymmetry`
  - `abs_z × sec_one_sided_recent_8k`
  - `divergence_sign × sec_recent_8k_count_asymmetry`
  - `aligned_relative_return_5d × tone_aligned_contrast`
  - `abs_z × tone_aligned_contrast`
  - `sentiment_both_known × tone_aligned_contrast`

**Families and grids:**

- logistic (median imputation, standardization) with
  C ∈ {0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1};
- XGBoost with six configurations: the two v2 configurations plus
  (depth 2, 400 trees, learning rate 0.03), (depth 3, 200, 0.05),
  (depth 4, 200, 0.03) and (depth 3, 400, 0.03). All use min_child_weight 20
  and lambda 10.

**Tuning:**

- Four forward folds (2016, 2017, 2018, 2019). Each fits on events whose full
  label window ends before the fold year and validates on in-year events whose
  window ends inside the year.
- Criterion: mean fold Brier score.
- A chooses a family and parameters. B chooses a family, parameters and a
  feature set from {B_both, B_lean, B_plus}. This extra search for B is
  disclosed, and B_both alone is also reported.
- The final fit covers all 2006–2019 events whose label window ends by
  2019-12-31.

**Calibration.** Monotone sigmoid on 2020–2021 margins, as in v2.

## Improvement 1: rank-based trading rule

- **Rule.** Select an event when its calibrated score is at least the model's
  own top-k quantile of calibration-period scores on the gating population.
  This gives A and B equal expected selection rates.
- **k** ∈ {10 %, 20 %, 33 %}; headline 20 %.
- **Gating population.** Either Baseline 1 (ACTIVE fresh events) or Baseline 0
  (all fresh events). The headline gate is the one with the higher mean net
  return per COMPLETE trade over 2006–2021 under the chosen exit. Both gates
  are reported.
- This amends the "same declared threshold" rule for these exploratory
  variants only. The Decision 36 threshold ladder stays as recorded.

## Improvement 3: B as a veto

- **Rule.** Trade every gated event except the model's bottom v of
  calibration-period scores.
- **v** ∈ {20 %, 33 %}; headline 20 %.
- **Purpose.** This tests whether B's information is better at removing likely
  failures than at picking winners.

## Pre-registered primary contrast

On the headline gate, the primary contrast is the economic target model,
selected by forward folds, under the top-20 % rule and the chosen exit, with
headline costs. The measure is the B − A difference in mean net return per
gated candidate: selected trades contribute their net return, withheld events
contribute zero, and unknown executions are excluded and counted. It uses 2,000
paired calendar-month bootstrap draws (seed 5557) over 2022–2023.

Secondary results, all reported:

- mean net return per COMPLETE selected trade and the hit rate;
- the veto variants and the other k values;
- the reversion-target models;
- the 10 bps per side cost stress;
- assessment ROC-AUC, PR-AUC and Brier for every model, with the paired
  calendar-quarter B − A Brier bootstrap (2,000 draws, as in v2).

## Outputs

Outputs go to `outputs/p6_improvement/<run_id>/`, which is gitignored. A
development stage writes `frozen_choices.json` (exit, gate, models, parameters,
thresholds and checksums) before any 2022–2023 metric is computed. That file's
checksum is recorded in DECISIONS before the evaluation stage runs. The results
are recorded in `docs/P6_IMPROVEMENT_RESULTS.md` and DECISIONS section 44.

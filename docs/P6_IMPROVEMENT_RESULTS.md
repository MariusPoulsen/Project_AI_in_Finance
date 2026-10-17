# P6 model and trading improvements: results (post-hoc exploratory)

Technical record of the pre-registered improvement experiment (DECISIONS 43, 43a
and 44; plan in `docs/proposals/P6_IMPROVEMENT_PLAN.md`). It is not the
academic report.

**Read this first.**

- **Evaluation window.** All numbers are for 2022–2023. Those years were
  already observed during development, so the results are **post-hoc
  exploratory**, not confirmatory.
- **Pre-registration.** Every choice was frozen on 2006–2021 data before
  evaluation (`frozen_choices.json`, SHA-256 `000953d6…`, commit `c6989ae`).
- **Coverage.** Every pre-registered variant is reported.
- **Final test.** It stays locked; only 2024–2025 can confirm anything here.
- **Scope.** h20 only. The frozen production policy (Decision 36) and the
  accepted P6 results (Decision 42) are unchanged.

Artifacts are in `outputs/p6_improvement/run1/` (gitignored): `frozen_choices.json`,
`models/` and `evaluation.json`. `evaluation-initial.json` is the first
evaluation output. It differs only by the missing Brier intervals (see
Decision 44).

## Primary pre-registered contrast: negative

The setup is the Baseline 1 (ACTIVE) gate, the trade-outcome target, the top
20 % rank rule, the chosen exit and headline costs. The measure is the B − A
mean net return per gated candidate (paired calendar-month bootstrap, 2,000
draws, seed 5557, 23 populated months, 257 common candidates).

**−13.8 bps per candidate, 95 % interval [−34.9, +4.5].** B does not beat A on
the pre-registered measure, and the point estimate favours A.

## Improvement-by-improvement findings

### 5. Exit rule

**Chosen:** no adverse stop, take-profit at |z| ≤ 0.25. It was the best of 8 on
2006–2019 (−5.7 against −13.5 bps for the frozen rule) and passed the
2020–2021 guard (+21.8 against −8.4 bps).

**Trade-everything results for 2022–2023, same events, headline costs:**

| Gate | Chosen exit | Frozen exit (Decision 42) |
|---|---|---|
| Baseline 0 | +2.6 bps | −3.6 bps |
| Baseline 1 | −20.2 bps | −19.2 bps |

The improvement shrank sharply out of sample. No bootstrap compares the two
exits, because that was not pre-registered. Dropping the stop raises tail risk.

### 2. Trading-outcome target: failed

On 2022–2023, the models predicting "this trade nets a profit" have ROC-AUC
**0.528 (A)** and **0.526 (B)**, with Brier scores 0.2494 and 0.2495 against
a coin-flip base rate. The traded outcome is essentially unpredictable from
the signal-time features. Every economic-target selection result below should
be read with that in mind.

### 4. Features and model families

- **Feature sets.** The forward folds chose B_both for both targets. Neither
  the lean set (sparse catalyst columns removed) nor the interaction set won.
- **Families.** The economic target used XGBoost for both A and B. The
  reversion target used logistic regression (C = 0.01) for A and XGBoost for B.

**Reversion-target forecast quality on 2022–2023** (3,430 labelled events, 248
positives):

| Model | ROC-AUC | PR-AUC | Brier |
|---|---:|---:|---:|
| A (logistic) | 0.736 | 0.158 | 0.06451 |
| B (XGBoost, B_both) | **0.760** | **0.168** | **0.06413** |

The paired calendar-quarter Brier bootstrap (8 quarters, 2,000 draws, seed 42,
as in v2) gives B − A = **−0.00038 [−0.00147, +0.00093]**. B is better on
every metric, but the improvement is not significant. Part of the gain may
come from the model family rather than B's information, because the folds
picked XGBoost for B and logistic for A.

### 1. Rank-based rule

The rule works mechanically. The table shows events selected at 2022–2023 on
the Baseline 1 gate, against 5 (A) and 8 (B) under the fixed 0.30 threshold:

| Target | k | A selected | B selected |
|---|---|---:|---:|
| Economic | 10 % | 20 | 16 |
| Economic | 20 % | 40 | 51 |
| Economic | 33 % | 78 | 92 |
| Reversion | 10 % | 5 | 13 |
| Reversion | 20 % | 24 | 46 |
| Reversion | 33 % | 75 | 94 |

**The gate choice failed out of sample.** Baseline 1 was chosen because it
earned +20.2 bps against −1.4 bps over 2006–2021. In 2022–2023 trading all of
Baseline 1 earns −20.2 bps against +2.6 bps for Baseline 0. The headline gate
was therefore the weaker population in the evaluation years.

### 3. Veto rule: no benefit

No veto variant beats A by a clear margin, on either gate or target. The B −
A estimates per candidate on Baseline 1 for the economic target are −12.8 bps
(drop the bottom 20 %) and −16.2 bps (drop the bottom 33 %). Both intervals
include zero.

## B − A per gated candidate, every rule and gate

These are headline costs, using the paired calendar-month bootstrap. Each
entry is the B − A estimate in bps with its 95 % interval.

| Gate | Target | Top 10 % | Top 20 % | Top 33 % | Veto 20 % | Veto 33 % |
|---|---|---|---|---|---|---|
| B1 | Economic | −20.6 [−39.0, −4.2] | **−13.8 [−34.9, +4.5]** (primary) | −5.2 [−28.4, +16.2] | −12.8 [−34.6, +5.7] | −16.2 [−43.3, +6.1] |
| B1 | Reversion | +1.1 [−15.6, +15.7] | −2.7 [−19.0, +15.4] | −9.6 [−41.0, +23.4] | +2.5 [−16.7, +22.1] | −1.4 [−20.1, +16.8] |
| B0 | Economic | −0.3 [−3.5, +2.6] | +1.5 [−4.0, +7.4] | +1.0 [−7.9, +10.1] | −0.9 [−7.4, +5.9] | −5.8 [−13.3, +2.4] |
| B0 | Reversion | +2.7 [−0.6, +6.5] | +4.1 [−1.5, +10.5] | +4.4 [−0.2, +9.0] | +3.9 [−1.9, +10.7] | +2.8 [−5.2, +11.4] |

**Mean net return per COMPLETE selected trade on the Baseline 0 gate**
(reversion target, headline costs; 10 bps per side in brackets):

| Rule | A: n, mean | B: n, mean |
|---|---|---|
| Top 10 % | 82, +6.4 (−3.8) | 185, +52.3 (+42.2) |
| Top 20 % | 337, +24.8 (+14.7) | 480, +46.5 (+36.3) |
| Top 33 % | 746, +21.3 (+11.2) | 810, +37.7 (+27.6) |

## Technical reading

These are observations, not claims.

1. **No pre-registered improvement makes B better.** The primary contrast
   favours A, and its interval includes zero.
2. **What doesn't work:** the trading-outcome target (unpredictable), the veto
   rule, and the Baseline 1 gate (it reversed out of sample).
3. **The most promising lead is not the primary.** On the broad Baseline 0
   population, the reversion-target B model with a rank rule is ahead of A at
   every k: +2.7 to +4.4 bps per candidate, with intervals that only just
   include zero, and better forecast metrics. This came from a non-headline
   cell of a 20-cell grid, chosen after viewing the results, so it is a
   hypothesis and not evidence.
4. **Recommendation for the final test.** If the owner wants a single B
   hypothesis for 2024–2025, pre-register exactly this:
   - reversion-target models with forward-fold-selected families (or the same
     family for A and B, to isolate B's information);
   - a top-20 % calibration-quantile rule on Baseline 0;
   - the frozen exit (the research exit did not hold up clearly);
   - one primary B − A per-candidate contrast.

   That is a methodology change to the Decision 36–42 freeze. It needs a new
   freeze manifest and the owner's explicit unlock, and it must not be retuned
   after viewing 2024–2025.

## Walk-forward replication of the lead (DECISIONS 45–46): fails

The Baseline 0 reversion-rank lead was pre-registered and then replicated on
the twelve years in which it was not discovered (2010–2021). Each year's
models trained only on earlier label windows, the top-20 % thresholds came from
the prior year's out-of-sample scores, and trades used the frozen exit and
headline costs.

| Pair | B − A per candidate, pooled 2010–2021 | 95 % interval | Years B > A |
|---|---|---|---|
| A and B both XGBoost (primary) | +1.11 bps | [−0.49, +2.79] | 8 / 12 |
| Logistic A, XGBoost B | +2.12 bps | [−0.26, +4.58] | 7 / 12 |

**Verdict:** the lead fails the pre-registered criterion (the interval must
lie above zero) and is not adopted.

B tends to edge out A slightly, which is consistent with its better forecast
metrics, but the economic difference is small and not significant. The
selected trades lose money in many years for both models. Per-year rows are in
`outputs/p6_improvement/walkforward/walk_forward.json`.

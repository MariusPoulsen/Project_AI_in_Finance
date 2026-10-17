# Phase 6 development backtest: accepted results record

Technical record of the official Phase 6 acceptance run, 2026-10-17. It is not
the academic report. Every number below comes from the verified artifacts listed
here; `reports.json`, `uncertainty.json`, `robustness.json`, `cost-grid.json`
and `portfolios.json` in each experiment hold the complete denominators.

## Read this first

- **Post-hoc development results.** 2022–2023 is the v2 assessment window that
  was already observed during development. These are **not final-test
  results**. The 2024–2025 final test remains locked.
- **Policies fixed before the run.** Every execution, threshold and analysis
  policy was frozen before any historical return was computed (DECISIONS
  36–39). The official diagnostics reproduced the provisional ones exactly, so
  the freeze stands unchanged.
- **Full System not run.** Full System is `NOT_RUN` (Decision 40). These are
  four-rung results: Baseline 0, Baseline 1, Model A and Model B.
- **Model samples are tiny.** At the headline 0.30 threshold, Model A selects 2–14
  events and Model B 2–23 per horizon. No economic comparison involving A or B
  supports a conclusion. All paired economic bootstrap intervals include zero.
- **Forecast quality is separate from profit.** The A/B forecast comparison of
  record is v2's canonical paired-quarter analysis. The descriptive metrics
  below do not replace it.

## Identity and verification

| Item | Value |
|---|---|
| Snapshot | `group-v2.zip`, SHA-256 `8acc3af0f0936d5511ab02c5f574ec4e90d27a78f3859d01481a3e566f3def3f`; `team.py check` passed for 11,864 files |
| Primary | `research_primary_5c01ab3d29c74e3e9154d9e3` (DECISIONS 34) |
| h20 experiment | `d828d7aceb30950536226f48185664440db6e34f0b7f5b342b706b21f669cab5` (evaluation `research_evaluation_16a431c4fea73ffd35f56062`, 25 combinations) |
| h10 experiment | `bea3126de965f3367b312a45c5f15d90ab1a223ddf2a1104a31f35c9ef79e11a` (evaluation `research_evaluation_219b30fcf452cd5e1609ec3c`, 4 combinations) |
| h30 experiment | `02a2c5fa68db6a479d49323170b127d78597b76ce8f5cffe4bafb4b3fc3e82eb` (evaluation `research_evaluation_bc319e752527bdd7f10ff0c2`, 4 combinations) |
| Verification | All three `VERIFIED_HISTORICAL_REPLAY`: a fresh rebuild from the bound sources, compared byte for byte |
| Freeze manifest | `2266d696115db4e15b469cff20f5d4378b5458353dcb05542b15b034f72bf7de`. All decisions are CLOSED except Full System, which is DEFERRED. `final-test-gate` reports locked. |
| Runtime | 135 minutes on one thread (`p6-acceptance`, branch `p6/historical-adapters`) |

Artifacts are written to `.acceptance/p6-official/`, which is gitignored and
content-addressed. Re-running `p6-acceptance` on the same snapshot reproduces
the same identities.

## Headline: 0.30 common A/B threshold, frozen headline execution policy

Abbreviations: **Priced** is COMPLETE trades. **NE** is not entered (mainly
β outside (0, 3] or a missing fill). **UP** is unpriced (mainly paths truncated
at 2023-12-29). Mean net return is per COMPLETE selected trade, in bps of entry
gross notional. Label success is the supervised target among labelled selected
events.

| Horizon | Strategy | Selected | Priced | NE | UP | Mean net (bps) | Label success |
|---|---|---:|---:|---:|---:|---:|---:|
| h20 | Baseline 0 | 3,558 | 3,153 | 299 | 106 | −3.6 | 7.2 % (n = 3,430) |
| h20 | Baseline 1 | 266 | 247 | 16 | 3 | −19.2 | 13.5 % (n = 260) |
| h20 | Model A | 5 | 4 | 1 | 0 | +1.8 | 2 / 5 |
| h20 | Model B | 8 | 7 | 1 | 0 | −82.4 | 3 / 8 |
| h10 | Baseline 0 | 4,305 | 3,880 | 362 | 63 | −3.5 | 2.3 % (n = 4,236) |
| h10 | Baseline 1 | 307 | 286 | 19 | 2 | −13.4 | 5.9 % |
| h10 | Model A | 2 | 2 | 0 | 0 | −57.5 | 1 / 2 |
| h10 | Model B | 2 | 2 | 0 | 0 | −57.5 | 1 / 2 |
| h30 | Baseline 0 | 3,179 | 2,781 | 268 | 130 | +11.4 | 13.8 % (n = 3,006) |
| h30 | Baseline 1 | 245 | 224 | 16 | 5 | −12.2 | 19.0 % |
| h30 | Model A | 14 | 12 | 2 | 0 | −98.8 | 4 / 14 |
| h30 | Model B | 23 | 21 | 2 | 0 | −71.8 | 6 / 23 |

**Threshold sensitivities at h20** (the selection counts are the binding fact):

| Threshold | A selected / priced | B selected / priced |
|---|---|---|
| 0.20 | 73 / 70, mean −2.2 bps | 85 / 79, mean −40.2 bps |
| 0.40 | 1 / 1 | 0 / 0 |
| 0.65 | 0 / 0 | 0 / 0 |

**Descriptive forecast metrics** on all labelled fresh events (identical
populations for A and B):

| Horizon | A AUC / Brier | B AUC / Brier |
|---|---|---|
| h10 | 0.749 / 0.0224 | 0.774 / 0.0224 |
| h20 | 0.733 / 0.0646 | 0.736 / 0.0646 |
| h30 | 0.695 / 0.1132 | 0.689 / 0.1135 |

## Cost and borrow sensitivity (h20, headline threshold)

Mean net bps per COMPLETE selected trade. The trade selection is identical in
every row, and no scenario is selected.

| Cost/side | Borrow | Baseline 0 | Baseline 1 | Model A | Model B |
|---|---|---:|---:|---:|---:|
| 2.5 bps | 0 % | +4.8 | −11.6 | +8.0 | −75.7 |
| 2.5 bps | 1 % | +1.5 | −14.2 | +6.9 | −77.4 |
| 2.5 bps | 3 % | −5.2 | −19.5 | +4.5 | −80.9 |
| 2.5 bps | 10 % | −28.5 | −38.0 | −3.8 | −93.0 |
| 5 bps | 0 % | −0.2 | −16.6 | +3.0 | −80.7 |
| **5 bps** | **1 %** | **−3.6** | **−19.2** | **+1.8** | **−82.4** |
| 5 bps | 3 % | −10.2 | −24.5 | −0.6 | −85.9 |
| 5 bps | 10 % | −33.5 | −43.0 | −8.9 | −98.0 |
| 10 bps | 0 % | −10.3 | −26.6 | −7.2 | −90.8 |
| 10 bps | 1 % | −13.6 | −29.2 | −8.4 | −92.5 |
| 10 bps | 3 % | −20.2 | −34.5 | −10.7 | −96.0 |
| 10 bps | 10 % | −43.5 | −53.0 | −19.0 | −108.1 |
| 20 bps | 0 % | −30.3 | −46.6 | −27.5 | −110.9 |
| 20 bps | 1 % | −33.7 | −49.2 | −28.7 | −112.7 |
| 20 bps | 3 % | −40.3 | −54.5 | −31.0 | −116.1 |
| 20 bps | 10 % | −63.6 | −73.0 | −39.3 | −128.2 |

## Paired calendar-month bootstrap

The common known allocation per raw candidate uses 2,000 draws with seed 5557
over 24 populated months. Every adjacent difference has a 95 % interval
containing zero:

| Horizon | B0 → B1 | B1 → A | A → B |
|---|---|---|---|
| h20 | +2.0 bps [−21.7, +21.9] | +1.2 [−1.5, +4.0] | −0.2 [−0.7, +0.3] |
| h10 | +2.5 [−15.3, +19.6] | +0.9 [−0.8, +2.6] | 0.0 [0.0, 0.0] |
| h30 | −12.3 [−46.1, +16.0] | +0.3 [−3.5, +3.9] | −0.1 [−1.2, +1.0] |

Natural selected-mean comparisons involving A or B have no interval, because
fewer than 12 months contribute.

## Secondary fixed-share portfolio (headline)

The portfolio starts at NAV 1, targets 25 % of NAV gross per entry and holds
one position per pair. The Baseline portfolios still hold positions on
2023-12-29, the last development session. Those positions are
`DEVELOPMENT_END_TRUNCATION`, so no terminal NAV is reported for them. The
table shows the last fully known close NAV from the bound marks instead.

| Horizon | Strategy | Final NAV | Last known close NAV | Max drawdown (known closes) |
|---|---|---:|---:|---:|
| h20 | Baseline 0 | undefined (truncated) | 1.0064 | −6.3 % |
| h20 | Baseline 1 | undefined (truncated) | 0.8843 | −14.1 % |
| h20 | Model A | 1.0001 | 1.0001 | −1.7 % |
| h20 | Model B | 0.9853 | 0.9853 | −4.4 % |
| h10 | Baseline 0 / 1 | undefined (truncated) | 0.9988 / 0.9175 | −4.9 % / −14.9 % |
| h10 | Model A = B | 0.9970 | 0.9970 | −1.4 % |
| h30 | Baseline 0 / 1 | undefined (truncated) | 1.0357 / 0.9094 | −4.2 % / −11.2 % |
| h30 | Model A / B | 0.9701 / 0.9619 | same | −4.8 % / −6.2 % |

## Technical reading

These are observations, not claims.

- **The development years show no evidence of a profitable strategy.** At the
  frozen headline costs, no strategy shows a positive economic effect beyond
  sampling noise.
- **Baseline 1 does not improve on Baseline 0 economically.** Restricting to
  econometrically valid (ACTIVE) pairs raises label success but lowers the
  mean net return at every horizon.
- **The model rungs select almost nothing.** The calibrated probabilities are
  low (the label base rate is 2–14 %), so the common 0.30 threshold admits only
  a handful of events. Economic A versus B comparisons are therefore
  uninformative. The forecast comparison remains v2's paired-quarter analysis.
- **About 8–9 % of fresh events are not entered.** The main cause is the β
  eligibility gate (positive β, at most 3). These rows stay in every
  denominator.

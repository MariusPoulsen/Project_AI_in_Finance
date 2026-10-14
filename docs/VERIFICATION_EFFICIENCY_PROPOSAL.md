# Proposed shared-source verification for v2

Status: authorized by the user on 2026-10-14; implementation and acceptance pending.
Prepared on 2026-10-14 before expanded model assessment results are available.

## Problem and recommendation

The three horizons use the same completed, target-independent 37,421-event SEC
feature batch. The current implementation reconstructs that entire identical
batch twelve times: before each fit, inside each fit's native verification, in
each separate verification command, and again for all three horizons during
publication. Small parser improvements have not established a large speed gain.

Replace twelve complete text reconstructions with **two genuinely independent
complete reconstructions** of all 37,421 events. Keep complete source/checkpoint
checksum checks between stages and all thirty native model/report replays. This
reduces the expensive text reconstruction count by ten (83%); it is not a measured
83% whole-pipeline runtime reduction. Hashing, fitting and other gates remain.

## Exact proposed sequence

1. Run the existing complete source verifier before any fitting. Start with a
   fresh private parser cache. Reconstruct every selected SEC evidence pack,
   acceptance/cutoff/issuer claim, extraction validation, stored FinBERT
   aggregation, all 62 feature columns, coverage denominator and frozen schedule.
   Verify every checkpoint and the complete bound raw-cache inventory.
2. Write an immutable source-verification receipt only after that verifier
   succeeds. Bind the exact registry, event population, intelligence/source
   manifests, feature/checkpoint/raw inventories, current verifier source and
   runtime. Identify this as the fitting-input proof, never builder evidence.
3. Before every fit or native verification, validate the proof's identity and
   recheck the complete bound file checksums. Any changed source, checkpoint,
   feature, code or runtime rejects the proof; it cannot silently refresh itself.
   Use the exact original full model cohorts, tuning budgets and chronology.
4. Fit all thirty predeclared models and perform the same native probability,
   calibration, report, subgroup and paired-comparison checks, including the
   separate verification commands and the 1e-12 reproduction tolerance.
5. Before publication, run a second complete source reconstruction with a new
   empty private parser cache. It must reconstruct all events and reproduce the
   exact same stored feature batch; it cannot consume the first parser cache or
   a builder-generated parser cache. Bind its successful independent receipt to
   the publication and repeat the required native checks for all thirty models.
6. Require both real source receipts, all genuine model-stage exits, complete
   native checks, the current hosted CI gate and the actual read-only app gate
   before accepting or promoting v2. Preserve failed and superseded attempts.

## Unchanged scientific protocol

- Registry `research_registry_0bd415d2a5af1f4891dc1f0d`; 250 issuers, 736 pairs,
  fixed orientations and the full 37,421-event source population.
- Exact SEC `source_v3` bytes, conservative acceptance-clock policy and prior
  NYSE-session VIX convention.
- Pinned FinBERT assets and `sec-sentence-quality-wordpiece-v2` preprocessing;
  full denominators and UNKNOWN rows retained.
- Frozen, target-blind 500-event catalyst schedule, original response bytes and
  provider budgets; no new model weights or provider requests.
- Quantitative Model A; every Model B ablation; both logistic and XGBoost
  families; 20-session primary and 10/30-session sensitivities; matching,
  forward tuning, purging, calibration and assessment rules unchanged.
- All prediction, uncertainty and report checks; no assumed Model B improvement
  or profitable backtest.
- Locked 2024–2025 outcomes remain locked. No assessment-driven data removal.

## Required engineering checks before launch

- Proof substitution, partial populations, another batch/registry, stale source
  code/runtime, changed raw files, altered checkpoints/features and invalid
  source-clock claims all fail closed.
- A fitting-input receipt cannot substitute for the second independent source
  reconstruction. A checksum-only or sampled audit cannot mint either receipt.
- Shared-input and original replay paths produce identical predictions, chosen
  parameters, calibration and reports on deterministic fixtures.
- Progress distinguishes source pass 1/2 and 2/2, source events N/37,421, complete
  checksum audit, tuning folds, fitted models, native checks and publication.
  A source-pass estimate excludes later fitting/publication work.
- Freeze and test the replacement code in isolation; obtain hosted Linux,
  Windows and Colab acceptance on its actual source revision; review the exact
  command and bound receipts before stopping the old run and launching.

## Authorization boundary

DECISIONS section 23 currently says: “Model fitting, native verification and
publication still perform unchanged fresh raw replay of every event”. This
proposal changes that engineering acceptance cadence. The user explicitly
approved the two-pass amendment on 2026-10-14; DECISIONS section 26 records it.
It does not authorize reducing the dataset,
changing the scientific protocol, marking pending results successful, or opening
the final test. The existing twelve-pass run stays unchanged until the replacement
passes its engineering and hosted-CI gates and its exact launch is reviewed.

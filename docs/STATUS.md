# Delivery status

Snapshot: 2026-10-10. The primary development workflow is research v2; actual
expanded A/B results and promotion to GitHub `main` remain pending.
[The plan](PLAN.md) tracks implementation stages. Detailed past acceptance records
are in [implementation history](archive/IMPLEMENTATION_HISTORY.md).

## Accepted development inputs

| Input | Accepted identity or scope |
| --- | --- |
| Universe | `universe_880ba35c09b7997d8a7e322d`; 250 issuers, 40 groups, 736 fixed pairs |
| Market | `market_0e7ddfd8382ca8a866f66bd1`; 2004–2023 development history |
| SEC metadata | `research_sec_5f856a4e440531e2742bf1d8`; immutable `source_v3`, 89,657 filings |
| Event registry | `research_registry_0bd415d2a5af1f4891dc1f0d`; all 736 pairs completed |
| Feature scope | 37,421 distinct development pair/time events; 500 scheduled catalysts |
| Chronology | Fit 2006–2019; forward tune 2018/2019; calibrate 2020/2021; assess 2022/2023 |
| Final outcomes | 2024–2025 locked |

The source/registry/adapters, model comparison, native verification and readiness
interfaces are implemented. Offline engineering checks do not establish completed
historical feature coverage or Model B improvement.

## Current feature generation

`development_detached_v2` launched from frozen source
`a02aadff17f4be98699780108292e51b95603361` through a WMI service-parent worker.
The pre-launch audit verified and copied 2,290 existing checkpoint files unchanged;
remaining events use the full frozen pipeline. Live counts and terminal status
belong to the saved operational records, not this static document:

```text
.acceptance/intelligence_20261010T002415Z_e7f267814826/launch.json
.acceptance/intelligence_20261010T002415Z_e7f267814826/progress.json
.acceptance/intelligence_20261010T002415Z_e7f267814826/stdout.log
.acceptance/intelligence_20261010T002415Z_e7f267814826/stderr.log
.acceptance/intelligence_20261010T002415Z_e7f267814826/exit.json
```

Audit: `.acceptance/detached_v2_checkpoint_audit.json`, SHA-256
`db64230b1259f0824e43041860e423c34491f9c00de831503cfbdf36b17dc839`.
New immutable inputs SHA-256:
`1aee1fa15376e5b842e3519d3dbb285750f129a47906e6be6626bc17487f4e43`.
Only engineering code identity changed from the stopped batch's scientific inputs.
The source, registry, quality-v2 policy, catalyst schedule and final lock were preserved.

Recovery verification passed 82 focused recovery/CLI/intelligence/worker checks,
67 evidence checks, Ruff, 147-file formatting and strict mypy for 79 files.
The network-free detachment fixture survived its launching shell and wrote exit 0.
The exact source's [PR CI](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/38008174822)
and [branch CI](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/38008170961)
both passed Windows/Linux and Colab jobs. These are engineering gates, not study outcomes.

A complete feature `manifest.json` is still required. Audited feature-build success
records independent raw verification as pending; later model/native/publication
stages must perform their fresh replay. Old supervisors and incomplete receipts
are not valid release receipts for this generation.

## Remaining release gates

1. Complete all 37,421 features and disclose source/inference coverage.
2. Fit all thirty predeclared bundles over the 20/10/30-session registries.
3. Independently reconstruct the matched comparisons, reports and native inference.
4. Record sample counts, positive outcomes, uncertainty and actual A/B results.
5. Publish verified readiness with the completed pipeline receipt and matching CI gate;
   check the read-only app, then merge the accepted v2 release to GitHub `main`.

The detached worker only builds features. No automatic fitting, publication or
merge follows it. Keep its live source checkout frozen; parallel documentation
cleanup is prepared separately. See [the runbook](RESEARCH_V2_RUNBOOK.md) for
manual status, recovery, evaluation and publication commands.

The [original experiment](archive/README.md#original-experiment), source snapshots,
models and Git history remain reference material. Their seven assessment events
and zero positives cannot establish predictive usefulness. The expanded study's
Model B improvement is still an objective, not a result. Later agents, the shared
simulator and final-test evaluation remain separate work under the plan.

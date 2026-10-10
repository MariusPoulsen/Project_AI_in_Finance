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

`development_detached_v2` exited 1 on 2026-10-10 at 04:29:49 UTC with
`RemoteDisconnected`, after saving 4,727 checkpoints. Its workers are absent
and no complete manifest exists. The exact failed request was not recorded.
The preserved failed-attempt baseline binds every checkpoint byte:

```text
.acceptance/detached_v2_failed_attempt_20261010T051843Z_6a54dac86d30/receipt.json
```

Baseline SHA-256:
`0a23c5445e4c35353117087b870920406c85fdbb432c17cfa1c8ed94d524242c`.
The original launch logs and receipts remain preserved. Its original source and
inputs are unchanged; the prior 2,290-checkpoint audit cannot authorize new code.

Recovery targets a distinct `development_prefetch_v2` batch after a new source
freeze, engineering checks and a fresh SHA-bound audit of all 4,727 checkpoints.
The mode overlaps one next-event SEC preparation with current-event scoring,
sharing one CPU model and preserving inference settings, event order, the
500-event Gemma schedule and final lock. Interrupted public-source transfers use
the existing bounded retry policy. No measured whole-job speedup is established.

Actual audit, launch, progress and exit facts belong to the new operational
receipts. The [runbook](RESEARCH_V2_RUNBOOK.md) describes the exact recovery and
manual-status commands; never infer a live worker from this static snapshot.

Local engineering validation passed 139 HTTP/CLI/launch checks, 50 intelligence/
checkpoint regressions plus both final audited-reuse cases, and 192 evidence/
extraction/SEC/schedule/parser/progress checks. Cold serial/prefetch fixtures are
byte-identical; deterministic barriers verify genuine overlap, one outstanding
source task, owner-thread confinement and ordered failure cleanup. Ruff passes,
all 155 Python files are formatted, strict mypy passes for 79 source files, the
PowerShell launcher parses, and all 132 local documentation links resolve.
These checks do not establish historical model gains or complete study acceptance.

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
merge follows it. Keep its live source checkout frozen after launch. See
[the runbook](RESEARCH_V2_RUNBOOK.md) for
manual status, recovery, evaluation and publication commands.

The [original experiment](archive/README.md#original-experiment), source snapshots,
models and Git history remain reference material. Their seven assessment events
and zero positives cannot establish predictive usefulness. The expanded study's
Model B improvement is still an objective, not a result. Later agents, the shared
simulator and final-test evaluation remain separate work under the plan.

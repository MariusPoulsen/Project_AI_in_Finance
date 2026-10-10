# AGENTS.md — AI Structural-Break Detector

This repository implements the FINS5557 Track A project **AI Structural-Break
Detector for Statistical Arbitrage**. Coding agents own implementation of the
research system, including finance/econometrics, ML, NLP/agents, backtesting,
software engineering, tests, UI, deployment support and technical run documentation.
The user owns the final academic report and presentation/video.

The authorized primary workflow is research v2. Complete its actual feature/model
and independent-verification gates before promoting it to GitHub `main`. Promotion
changes the default workflow; it does not overwrite the original experiment sources,
protocol, artifacts or Git history. Pending results must remain pending, and Model B
improvement is a research objective rather than an assumed outcome.

## Read only what you need

Before substantial work, read in this order:

1. `docs/DECISIONS.md` — canonical decisions, including the v2 amendments and promotion;
   overrides conflicting or stale wording elsewhere.
2. The active work/gate in `docs/PLAN.md`.
3. For primary research, `docs/RESEARCH_V2_PROTOCOL.md` and the relevant section of
   `docs/RESEARCH_V2_RUNBOOK.md`; otherwise only the relevant specification(s).

Use `docs/specs/README.md` to find component specifications. Original experiment runbooks in `docs/archive/reference/`
and configurations remain reference contracts; their old dates/populations are not
the primary v2 defaults. Do not parse the archival PDFs when Markdown equivalents exist.

## Architecture and workflow constraints

- Use the modular Python monolith; do not add FastAPI/microservices without an
  authorized architecture change. Streamlit is presentation only; domain logic
  belongs in packages/services. Keep orchestration imports acyclic.
- Canonical analytical writes occur in explicit batch jobs. Ordinary app browsing
  is read-only and must not initiate downloads, LLM calls, fitting or publication.
- V2 uses the separate `data/research_v2` workspace and exact registered generation
  identities. Preserve original workspaces, versioned configurations and stored
  source bytes. Do not select generations from directory modification times.
- In this checkout, `structural-break` is the primary research CLI;
  `structural-break-research` remains compatible, and `structural-break-reference`
  exposes the original reference commands. GitHub `main` remains on the earlier
  release until v2 acceptance. Keep reference reproduction explicit.
- Do not add models, data sources or subsystems merely for sophistication.

## Scientific invariants

These are release blockers:

- **Point-in-time correctness:** predictors and evidence must be admissible by
  event close. Future observations are allowed only for development label
  construction or an explicitly authorized outcome/backtest run. Use the previous
  NYSE session's VIX, conservative SEC clock bounds and issuer continuity checks.
  Missing/ambiguous evidence stays UNKNOWN; it is not neutral or confirmed absence.
- **Chronology:** primary sources start in 2004; the 504-session formation warm-up
  permits eligible FIT events from 2006. Fit through 2019, tune on forward 2018/2019
  folds, calibrate on 2020–2021 and assess on 2022–2023. Purge complete target
  windows at every partition/fold boundary; fit transformations only within their
  fitting period. Preserve original 2016–2021/2022–2023 contracts when replaying v1.
- **Final-test lock:** 2024–2025 outcome/performance results remain locked until
  the methodology is frozen and the user explicitly authorizes the final run.
  Primary-v2 promotion alone is not final-test authorization.
- **Frozen population/orientation:** preserve the 250-issuer, 736-pair business-peer
  roster and original 28 pair orientations; added orientations follow frozen
  security identity. Do not search both Engle–Granger directions or select pairs
  using outcomes. The primary population is estimable fresh divergences; report
  ACTIVE as an exploratory subset, not a rebuilt trading cohort.
- **Matched model comparison:** A and B share observations, targets, quantitative
  columns, chronology, tuning budget, fitted-preprocessing and calibration rules.
  Keep UNKNOWN rows in the comparison. The primary is calibrated logistic B-both
  versus A at 20 sessions; retain all ablations, both families and 10/30-session
  sensitivities. Do not select a favorable horizon/subgroup after assessment.
- **Honest inference:** report denominators, positive outcomes, source coverage,
  losses and paired calendar-quarter uncertainty, including inconclusive/negative
  results. The assessment has only eight quarter blocks. Previously observed
  original-pair results are development information. Forecast gains do not prove
  economic profitability.
- **Historical text:** bind exact issuer/chunk/offset/timestamp provenance and
  pinned FinBERT assets/policy. Quality-v2 exclusions and budget omissions retain
  full raw coverage denominators; legacy policies/caches remain exactly replayable.
  Modern pretrained models used on earlier SEC text are a disclosed retrospective
  assumption, not models available in that earlier information set.
- **Affordable extraction:** the frozen 500-event Gemma catalyst schedule is target
  blind and distinct from full SEC/metadata/FinBERT coverage. Unscheduled or invalid
  catalysts remain UNKNOWN. Enforce the configured call budget including retries;
  paid API use is disabled. Flash remains reserved for later agents.
- **Model ladder/controller:** A is quantitative; B adds structured SEC features;
  the Full System adds source-grounded agents and a deterministic controller.
  LLMs do not directly set the final trade/research status.

The surviving-issuer roster, current business classifications, retrospective Yahoo
adjustments and modern text models are disclosed limitations. Do not claim a
historically complete investable universe, a vintage feed or familywise-controlled
ACTIVE screening.

## Engineering expectations

- Use tested Python modules, Python 3.11, `uv`, the committed lockfile, pytest,
  Ruff and strict type/data validation. Keep notebook cells as launchers.
- Normal CI uses deterministic fixtures with blocked network sockets, not paid
  APIs or downloaded model weights. Real-source/inference and actual-evaluation
  acceptance are separate gates.
- Keep provider/model selection configurable, expensive outputs versioned/cached
  and required lineage preserved. Registered outputs are immutable; changed
  scientific inputs or code require a new generation.
- Do not edit computational source while a registry/model batch is running: the
  computational identity hashes package source. Prepare changes in isolation and
  coordinate synchronization after the active frozen jobs finish.
- Never repair a failed checksum by rewriting a registered manifest. Verify
  checkpoint identity before resuming; do not assume a RUNNING record is dead.
- For the explicitly authorized detached recovery, follow DECISIONS section 23:
  a SHA-bound checkpoint preflight may avoid repeated builder replay of verified
  stored outputs. Independent scientific verification remains a fresh raw replay.
  Let detached jobs run without continued chat polling; report the manual status
  command and keep source frozen until the worker exits.
- Promotion requires explicit accepted publication identities and independent
  verification. App readiness must fail clearly for missing/incomplete artifacts,
  with no automatic fallback to a sensitivity or a newer unverified directory.
  Use `structural-break promote-primary --pipeline-receipt PATH --ci-gate PATH`
  only with the completed genuine three-horizon receipt and its bound hosted-CI
  evidence. The job performs fresh source/native replay before publication.
  Set `SB_WORKSPACE_ROOT` for a relocated workspace in both CLI and app; an
  explicit CLI `--workspace-root` takes precedence.

## Execute the plan and resolve ambiguity

Implement a coherent slice, add meaningful deterministic checks, run the required
lint/type/test and acceptance gates, then record status/decisions. Do not proceed
through a failed scientific or engineering gate.

For unspecified engineering details that do not change scientific meaning, choose
a conventional implementation and document it. Changes to information sets,
labels, universe, model comparisons, admissibility, execution assumptions or
final-test integrity must follow the canonical decisions and protocol. The user
has delegated research design, but that is not permission for undisclosed
assessment-driven changes. Record authorized amendments with their actual timing
and preserve the prior protocol/artifacts.

Do not draft the user's academic report or presentation unless explicitly asked.
Maintain the technical documentation needed to run, reproduce, test and demonstrate
the system.

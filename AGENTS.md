# AGENTS.md — AI Structural-Break Detector

This repository implements the FINS5557 Track A project **AI Structural-Break Detector for Statistical Arbitrage**. Coding agents own the full implementation of the research system, including finance/econometrics, ML, NLP/agents, backtesting, software engineering, tests, UI, deployment support, and technical run documentation. The user owns the final academic report and presentation/video.

## Read only what you need

Before substantial work, read in this order:

1. `docs/DECISIONS.md` — canonical decisions; overrides conflicting or stale wording elsewhere.
2. The active phase in `docs/PLAN.md` — scope and acceptance gate.
3. Only the relevant file(s) in `docs/specs/` for the task.

Use `docs/specs/README.md` to find the right specification. Do not parse `docs/PDFs/` during normal implementation when the Markdown equivalent exists.

## Architecture constraints

- Use the specified modular Python monolith; do not add FastAPI/microservices unless the user changes the architecture.
- Streamlit is presentation only. Domain logic belongs in packages/services.
- Cross-package orchestration belongs in services/jobs; keep imports acyclic.
- Canonical analytical writes happen in explicit batch jobs; ordinary app browsing is read-only.
- Use the canonical storage paths and repository conventions from `docs/DECISIONS.md` and the software-engineering spec.
- Do not add major models, data sources, or subsystems merely for sophistication.

## Scientific invariants

These are blockers, not suggestions:

- **Point-in-time correctness:** for event time `t0`, every predictor/evidence item must have been available at or before `t0`. Future data is allowed only for label construction and realised backtest outcomes.
- **Chronological evaluation:** training 2018–2021, validation 2022–2023, final test 2024–2025, with the specified embargo and training-only fitted transformations.
- **Final-test lock:** implement the final-test path, but do not inspect/tune against headline 2024–2025 results until the methodology is frozen and the user explicitly authorises the final run.
- **Fixed pair orientation:** use the pair universe/orientations in `docs/DECISIONS.md`; do not search both Engle–Granger directions and keep the best.
- **Historical text evidence:** headline Model B / Full-System historical evaluation uses admissible SEC evidence according to the specs.
- **Model ladder:** Model A = quantitative features; Model B = Model A + structured point-in-time event features; Full System = Model B + source-grounded agents + deterministic controller.
- **Deterministic final decision:** LLMs may extract/analyse evidence, but they do not produce the final trade/research status directly.

## Engineering expectations

- Implement production project logic in tested modules, not notebooks or pseudo-code.
- Use Python 3.11, `uv`, the committed lockfile, pytest, Ruff, and the typed/data-validation tooling defined in the specs.
- Add tests and deterministic fixtures with each phase; normal CI must not require live external APIs or paid LLM calls.
- Leakage/timestamp failures are release blockers.
- Keep LLM provider/model selection configurable; do not hardcode a vendor in domain logic.
- Cache/version expensive historical agent outputs as specified.
- Preserve lineage and reproducibility metadata required by the relevant component specification.

## How to execute `docs/PLAN.md`

For each phase:

1. Read the phase and relevant specification(s).
2. Implement the phase as one coherent vertical slice where practical.
3. Add tests/fixtures in the same change.
4. Run required lint, type, test, and acceptance checks.
5. Update `docs/PLAN.md` status/check boxes and record material implementation decisions.
6. Do not continue through a failed scientific or engineering gate.

Large coding-agent steps are encouraged when they remain reviewable and respect these gates.

## Ambiguity rule

If an unspecified engineering detail does **not** change scientific meaning, choose a conventional solution and document it briefly.

If a choice can change the information set, labels, pair universe, model comparison, evidence admissibility, execution assumptions, or final-test integrity, do not improvise silently. Resolve it using `docs/DECISIONS.md` and the relevant spec; if still unresolved, leave a clear blocker for the user.

## Out of scope unless explicitly requested

Do not spend implementation time drafting the final academic report or presentation/video. Do create the technical documentation required to run, test, reproduce, deploy, and demonstrate the system.

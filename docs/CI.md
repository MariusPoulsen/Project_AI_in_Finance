# GitHub Actions validation

Routine pull requests targeting `main` or `research-v2`, and pushes to `main`,
run two Linux jobs in parallel:

- `foundation (ubuntu-latest)`: locked dependencies, Ruff, formatting, strict
  mypy and the full pytest suite. pytest runs one process per runner CPU
  (`pytest-xdist`, `-n auto --dist loadfile`) and prints the 25 slowest tests.
  `loadfile` keeps each test file on one worker, so module-scoped synthetic
  pipeline fixtures are built once instead of once per worker.
- `acceptance (ubuntu-latest)`: the synthetic data, econometric and Models A/B
  build, replay, verify and reload checks through the CLI.

Every pull request runs both jobs, including documentation-only changes:
`tests/unit/test_config.py` reads `docs/DECISIONS.md`, so documentation can
break tests. Pushes to `main` confined to `docs/**`, `README.md`, `AGENTS.md`
or `LICENSE` skip the duplicate run after merging. Superseded routine runs are
cancelled.

The `main` branch ruleset requires a pull request, resolved review conversations
and `foundation (ubuntu-latest)` from GitHub Actions. It blocks deletion and force
pushes and applies to administrators. No reviewer approvals are mandatory for
this sole-maintainer repository. Keep the `foundation` job id and matrix so the
required check name stays unchanged; add `acceptance (ubuntu-latest)` to the
ruleset to make the CLI checks required as well.

The manual workflow input `full_validation` defaults to `true`. It runs the same
two jobs on both `ubuntu-latest` and `windows-latest`, plus `nlp-runtime`, which
installs the optional CPU PyTorch/Transformers extra and imports it. Foundation
jobs have a 45-minute timeout. Manual runs have distinct concurrency groups and
are not cancelled when another run starts. A manual run with
`full_validation=false` performs only the Linux jobs.

Routine Linux validation alone cannot qualify as the full research release CI
gate. Release evidence must retain every successful full-validation job and bind
the actual tested Git revision and computational source to the completed genuine
pipeline. Earlier release evidence, including runs with the retired
`colab-bootstrap` job, remains valid for the revisions it recorded; do not
substitute a newer workflow result for recorded CI evidence. Synthetic hosted
checks do not establish that the 37,421-event feature build or actual model
evaluation has completed.

The active local research checkout must remain frozen while its detached batch
runs. Prepare and push CI-only changes from a separate checkout and do not pull
them into that checkout until its frozen jobs have exited.

Request a full validation of a reviewed branch with:

```powershell
gh workflow run ci.yml --repo MariusPoulsen/Project_AI_in_Finance --ref BRANCH -f full_validation=true
```

Record the branch's exact revision first, and check afterwards that the run
tested that revision and that every expected job succeeded. The 2024–2025 final
test remains locked.

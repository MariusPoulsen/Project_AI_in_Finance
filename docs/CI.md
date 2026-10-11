# GitHub Actions validation

Routine pull requests targeting `main` or `research-v2`, and pushes to `main`,
run the complete Linux foundation job. It retains the full pytest suite, locked
dependencies, Ruff, mypy and all existing synthetic data, econometric and Models
A/B build, replay and reload checks. Branch pushes no longer repeat the checks
already triggered by an open pull request. Superseded routine runs are cancelled.

Every pull request runs Linux CI, including documentation-only changes, so the
required check is always reported. Pushes to `main` confined to `docs/**`,
`README.md`, `AGENTS.md` or `LICENSE` skip the duplicate run after merging.
Workflow, lockfile, scripts, source, tests and other changes still trigger it.

The `main` branch ruleset requires a pull request, resolved review conversations
and `foundation (ubuntu-latest)` from GitHub Actions. It blocks deletion and force
pushes and applies to administrators. No reviewer approvals are mandatory for
this sole-maintainer repository. Windows and Colab remain separate release gates.

The manual workflow input `full_validation` defaults to `true`. This runs exactly
the three complete release jobs: `foundation (ubuntu-latest)`,
`foundation (windows-latest)` and `colab-bootstrap`. The Windows foundation and
Colab commands retain their complete previous checks. Foundation jobs have a
60-minute timeout and Colab has a 30-minute timeout. Colab also caches its uv
dependencies. Manual runs have distinct concurrency groups and are not cancelled
when another run starts. A manual run with `full_validation=false` performs only
the Linux foundation job.

Routine Linux validation alone cannot qualify as the full research release CI
gate. Release evidence must retain all three successful jobs and bind the actual
tested Git revision and computational source to the completed genuine pipeline.
Keep the already completed full push and pull-request runs for frozen revision
`f3545bcda87fe1c816224e74613de296646647b0` intact. Their evidence remains distinct
from any later CI policy run. Synthetic hosted checks do not establish that the
37,421-event feature build or actual model evaluation has completed.

The active local research checkout must remain frozen while its detached batch
runs. Prepare and push CI-only changes from a separate checkout. The remote
branch can receive this workflow policy while the running checkout keeps its
exact committed revision and file bytes; do not pull the changes into that
checkout until its frozen jobs have exited and their bindings are preserved.
Do not change a release receipt or substitute a newer workflow result for its
recorded CI evidence.

After this workflow is available on the default branch and the reviewed
`research-v2` branch contains it, a future full validation can be requested with:

```powershell
gh workflow run ci.yml --repo MariusPoulsen/Project_AI_in_Finance --ref research-v2 -f full_validation=true
```

Before dispatch, record the reviewed branch's exact revision. After completion,
check that the run tested that revision and that all three expected jobs succeeded
before binding its immutable evidence into a release gate. The command above is
an instruction for a future release; preparing the policy does not dispatch it,
merge `research-v2` into `main`, or publish the study. The 2024–2025 final test
remains locked.

# Run the primary research workflow in Google Colab

Colab launches the same Python package and explicit batch jobs used locally.
The project runs in its own Python 3.11 `.venv` using the committed `uv.lock`,
even when the notebook's host kernel uses another Python version. Do not copy the
Windows course environment into Colab. No JupyterLab, ipykernel, widgets or notebook
package is required by the project.

Research v2 is the primary development workflow: 250 frozen issuers, 736 fixed
pairs, separate SEC/FinBERT/Gemma evidence and matched A/B evaluation. Full feature
generation, actual model evaluation and promotion to GitHub `main` are pending.
Check [STATUS.md](STATUS.md) for the accepted source revision and gates before
running or interpreting results. A source clone contains no generated research
workspace, API credentials or FinBERT weights.

## 1. Get the reviewed v2 source

For a private repository, upload a GitHub source ZIP and extract it to
`/content/Project_AI_in_Finance`, or use this hidden-token clone cell. Supply a
short-lived token with read access. The token is passed only through the clone
process environment; it is not stored in the remote URL, files or output.

Choose a reviewed v2 commit/tag from the completion evidence. While promotion is
pending, `origin/research-v2` is the research branch; do not assume the current
`origin/main` already contains the promoted interface. After acceptance, use the
recorded promotion commit/tag for a reproducible run.

```python
import base64
import getpass
import os
import subprocess

repository = "/content/Project_AI_in_Finance"
source_ref = input("Reviewed v2 commit/tag or origin/research-v2: ").strip()
if not source_ref or source_ref.startswith("-"):
    raise ValueError("Enter an explicit reviewed source reference")
token = getpass.getpass("GitHub token (read access): ")
clone_env = os.environ.copy()
clone_env.update(
    {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": "Authorization: Basic "
        + base64.b64encode(("x-access-token:" + token).encode()).decode(),
        "GIT_CONFIG_KEY_1": "credential.helper",
        "GIT_CONFIG_VALUE_1": "",
    }
)
try:
    subprocess.run(
        [
            "git",
            "clone",
            "https://github.com/MariusPoulsen/Project_AI_in_Finance.git",
            repository,
        ],
        env=clone_env,
        check=True,
    )
finally:
    del token, clone_env

reviewed_commit = subprocess.check_output(
    ["git", "rev-parse", "--verify", source_ref + "^{commit}"],
    cwd=repository,
    text=True,
).strip()
subprocess.run(
    ["git", "checkout", "--detach", reviewed_commit],
    cwd=repository,
    check=True,
)
print("Source commit:", reviewed_commit)
```

For a public repository, an ordinary clone needs no token; still select the reviewed
commit explicitly. A ZIP also needs a recorded source revision for reproduction.

## 2. Install the locked Python 3.11 environment

```python
%pip install uv==0.12.20
```

```python
import subprocess
import sys

repository = "/content/Project_AI_in_Finance"
workspace = "/content/research-v2-workspace"
subprocess.run(
    [
        sys.executable,
        repository + "/scripts/colab_bootstrap.py",
        "--nlp",
        "--workspace-root",
        "/content/bootstrap-checks",
    ],
    check=True,
)
```

The bootstrap installs Python 3.11 through uv, synchronizes the frozen environment
and runs its offline checks in a separate fixture workspace. It does not construct
the real study or call an LLM. Python/dependency installation requires internet.
The `--nlp` flag installs and retains local FinBERT dependencies. Subsequent
`uv run` commands must also retain `--extra nlp` when using that extra, or uv may
remove it during synchronization.

The Linux lock selects CPU PyTorch and the current CLI uses CPU inference.
Selecting a Colab GPU alone does not change this pipeline. Gemma uses direct Google
REST; the optional `agents` extra and paid API access are not needed.

The promoted primary CLI is `structural-break`; `structural-break-research`
remains a compatible alias. On the pre-promotion source, set `research_cli` to
`"structural-break-research"` below.

```python
research_cli = "structural-break"  # Use the research alias before promotion.
subprocess.run(
    ["uv", "run", "--frozen", "--extra", "nlp", research_cli, "--help"],
    cwd=repository,
    check=True,
)
```

## 3. Select a workspace and credentials

Keep active DuckDB files, source checkpoints and the virtual environment on local
`/content`, not an active Google Drive mount. Reproduction uses the verified
frozen workspace and exact registered versions from the accepted publication.
Restore that workspace before proceeding. To create a different source capture,
use a new workspace and disclose its new identity.

Add Colab Secrets named `SB_SEC_USER_AGENT` and `SB_LLM_API_KEY` and grant the
notebook access. The SEC value is a project name and real contact email, not a
login. The Google key is for the free guarded Gemma extraction. No Yahoo, SEC
account or database login is required. Never print secrets or put them in YAML,
Git, notebook literals or command arguments.

Use this launcher so only commands requiring a credential receive it:

```python
import os
import subprocess


def research_job(arguments, *, sec=False, gemma=False):
    child_env = os.environ.copy()
    try:
        if sec or gemma:
            from google.colab import userdata

            if sec:
                child_env["SB_SEC_USER_AGENT"] = userdata.get("SB_SEC_USER_AGENT")
            if gemma:
                child_env["SB_LLM_API_KEY"] = userdata.get("SB_LLM_API_KEY")
        subprocess.run(
            [
                "uv",
                "run",
                "--frozen",
                "--extra",
                "nlp",
                research_cli,
                *arguments,
                "--workspace-root",
                workspace,
            ],
            cwd=repository,
            env=child_env,
            check=True,
        )
    finally:
        del child_env
```

## 4. Sources, registry and SEC features

For a new full workspace, run the stages explicitly:

```python
research_job(["freeze-universe"], sec=True)
research_job(["capture-market"])
research_job(["collect-sec", "--sec-source", "source_v3"], sec=True)
research_job(["build-registry", "--workers", "2"])
```

The registry command prints `research_version`. Use that exact registered version;
do not select a directory by modification time. The frozen roster has 250 issuers
and 736 pairs, retaining the original 28 orientations. Development sources cover
2004–2023; 2004–2005 provide formation warm-up. Equity gaps remain missing,
previous-session VIX is used, and admissible SEC evidence uses conservative clock
bounds and issuer continuity.

The full job schedules 37,421 distinct pair/time observations across the three
horizons. The earlier partial quality batch was intentionally stopped with 1,494
checkpoints preserved; the replacement `development_primary_v2` awaits reviewed
operational fixes and source freeze. This union is not the assessment sample or
a success count.
Source failures/exclusions and UNKNOWN evidence remain explicit. Partial source
flags are dry runs, not complete studies. Keep computational package source
unchanged while registry/model jobs run.

```python
registry_version = input("Exact successfully registered research_version: ").strip()
batch_name = "development_primary_v2"
research_job(
    [
        "build-intelligence",
        "--registry-version",
        registry_version,
        "--batch-name",
        batch_name,
        "--sec-source",
        "source_v3",
        "--sentiment-preprocessing",
        "sec-sentence-quality-wordpiece-v2",
        "--catalyst-max-events",
        "500",
        "--download-model",
    ],
    sec=True,
    gemma=True,
)
```

`--download-model` permits acquiring the pinned public FinBERT assets; omit it
once they are cached in `repository/data/cache/huggingface`. Local inference is
cached by exact text, revision and preprocessing policy. The quality guard retains
source offsets and raw coverage denominators. Excluded/unscored text is disclosed;
UNKNOWN is not neutral.

The separate 500-event Gemma pilot is balanced by year/business group without
labels or scores, with a 1,000-call ceiling including retries. Unscheduled,
unavailable or rejected catalysts remain UNKNOWN. The pilot does not limit full
SEC source, metadata or FinBERT scheduling. Flash is reserved for later agents.
Do not change the frozen schedule or policy to improve assessment results.

Use a new immutable batch for changed inputs. An identical interrupted invocation
can reuse verified checkpoints; it cannot overwrite completed outputs. Read
[the batch runbook](RESEARCH_V2_RUNBOOK.md) for recovery, exact source-v3 identities,
legacy-policy replay and partial flags. The old incomplete evidence batch and the
original experiment remain preserved.

## 5. Fit and independently verify A/B

Fit 2006–2019, tune on forward 2018/2019 folds, calibrate on 2020–2021 and assess
on 2022–2023. Full target horizons are purged at partition/fold boundaries.
**2024–2025 outcomes remain locked**; promotion to the primary workflow does not
authorize opening them.

```python
for horizon in (20, 10, 30):
    research_job(
        [
            "train-models",
            "--registry-version",
            registry_version,
            "--batch-name",
            batch_name,
            "--horizon",
            str(horizon),
        ]
    )
```

Each command prints an evaluation version. Verify all three, without API access:

```python
for horizon in (20, 10, 30):
    model_version = input(f"Exact printed evaluation version for h{horizon}: ").strip()
    research_job(["verify-models", "--model-version", model_version])
```

Verification reloads native estimators/calibrators and reconstructs the matched
comparison and source/evidence parents. The primary is calibrated logistic B-both
versus A at twenty sessions. Report all families/ablations and ten-/thirty-session
sensitivities, denominators, successes, coverage and paired uncertainty. Negative
and inconclusive results remain valid results; no B improvement is assumed.

Once the genuine three-horizon pipeline is complete, publish the exact verified
generation using its completed operational receipt and bound hosted-CI evidence:

```python
pipeline_receipt = input("Completed verified pipeline receipt path: ").strip()
ci_gate = input("Exact bound hosted-CI receipt path: ").strip()
research_job(["promote-primary", "--pipeline-receipt", pipeline_receipt, "--ci-gate", ci_gate])
```

The command performs fresh source and native-model checks, then prints
`primary_version`. An incomplete run or fixture receipt cannot publish readiness.
Restore these exact receipts with the workspace when publishing from another
machine; do not fabricate completion evidence or choose another generation.

The survivor-conditioned roster, current business groups, retrospective Yahoo
adjustments and modern FinBERT/Gemma historical extraction are disclosed research
limits. Forecast improvement is not economic profitability. Read
[the protocol](RESEARCH_V2_PROTOCOL.md) before interpreting reports.

## 6. Preserve state and use the app

Colab machines are temporary. After all jobs close database connections, archive
the actual research workspace and download it or copy the archive to Google Drive.
Restore to local `/content` before the next session; never run the active database
directly on a Drive mount.

```python
import shutil
from google.colab import files

archive = shutil.make_archive(
    "/content/research-v2-workspace",
    "zip",
    root_dir=workspace,
)
files.download(archive)
```

This archive includes workspace sources, checkpoints and fitted artifacts, not the
repository's virtual environment, local `.env` or separate public FinBERT asset
cache. Reinstall the frozen environment after restoring the reviewed source.
Restore the asset cache separately or permit a fresh pinned download. Reverify
the exact restored publications before reporting results; do not rewrite manifests
to bypass a compatibility or checksum failure.

The promoted read-only Streamlit app uses the accepted v2 publication; local launch
is `uv run --frozen streamlit run app/streamlit_app.py`. A clone without the
generated workspace cannot display actual results. Colab supports the batch
workflow; a public app deployment/tunnel is not required for it. The accepted
publication/readiness instructions are recorded in [STATUS.md](STATUS.md).
For a relocated local workspace, set `SB_WORKSPACE_ROOT` in the ignored local
environment before launching the app. The CLI also accepts this setting, with
explicit `--workspace-root` taking precedence.

## Original experiment and offline checks

The original Phase 0–4 runbooks remain reference material:
[data](DATA_RUNBOOK.md), [econometrics](ECONOMETRICS_RUNBOOK.md),
[Model A](ML_RUNBOOK.md) and [SEC/Model B](INTELLIGENCE_RUNBOOK.md).
Use their historical checkout/versions or the promoted
`structural-break-reference` command with a separate original workspace.
Its 2014–2025 sources and 2016–2021/2022–2023 train/validation dates are not the
primary v2 chronology. The original final-outcome lock remains intact.

The bootstrap's optional `--data-fixture --relationship-fixture --ml-fixture
--intelligence-fixture` flags exercise the reference pipeline using synthetic
data/mock extraction, not live providers. Keep those fixtures separate from the
real workspace. Normal project tests also need no credentials, weights or API:

```python
subprocess.run(
    ["uv", "run", "--frozen", "pytest"],
    cwd=repository,
    check=True,
)
```

References: [uv Python installation](https://docs.astral.sh/uv/guides/install-python/),
[uv frozen synchronization](https://docs.astral.sh/uv/concepts/projects/sync/),
[Colab Secrets API](https://github.com/googlecolab/colabtools/blob/main/google/colab/userdata.py),
[Colab runtime lifecycle](https://research.google.com/colaboratory/faq.html).

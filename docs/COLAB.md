# Run research v2 in Google Colab

Colab launches the same package and explicit batch jobs used locally. The project
uses Python 3.11 in its own `.venv` and the committed `uv.lock`, independently of
the notebook kernel. No JupyterLab, ipykernel or widgets package is required.

The current local 37,421-event build is `development_detached_v2` at `a02aadf`;
model fits, independent acceptance and GitHub `main` promotion remain pending.
See [status](STATUS.md) and the [protocol](RESEARCH_V2_PROTOCOL.md). A source clone
contains no research workspace, credentials or FinBERT weights. A fresh Colab
capture creates a different generation; reproduction restores exact frozen state.

## Get the source

While promotion is pending, use `research-v2` or its reviewed commit, rather than
assuming `main` has the v2 interface. Select an explicit source revision for every
reproducible run.

For a private repository, upload and extract a source ZIP to
`/content/Project_AI_in_Finance`, or use this hidden-token clone cell with a
short-lived read-access token. The token is passed through the clone environment
and is not stored in the remote URL or notebook output.

```python
import base64
import getpass
import os
import subprocess

repository = "/content/Project_AI_in_Finance"
source_ref = input("Reviewed commit/tag or origin/research-v2: ").strip()
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

A public clone needs no token; still check out the reviewed commit explicitly.
Record the source revision if using a ZIP.

## Install the locked environment

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
research_cli = "structural-break"
subprocess.run(
    ["uv", "run", "--frozen", "--extra", "nlp", research_cli, "--help"],
    cwd=repository,
    check=True,
)
```

The bootstrap installs Python 3.11 and verifies infrastructure in a separate
offline fixture workspace; it does not build the actual study or call an LLM.
Dependency installation requires internet. Retain `--extra nlp` on subsequent
FinBERT commands so uv keeps the extra installed. Linux uses CPU PyTorch; choosing
a Colab GPU alone does not change inference. Gemma uses direct REST and needs
neither the optional `agents` extra nor paid API access.

`structural-break-research` remains a compatible research alias. The reference
CLI and optional synthetic bootstrap checks are documented in the
[archive](archive/README.md).

## Workspace and credentials

Keep active databases, checkpoints and the environment on local `/content`.
Restore a verified workspace there for reproduction. For a new capture, select
a new workspace; do not overwrite an existing registered generation.

Add Colab Secrets `SB_SEC_USER_AGENT` (project name and a real SEC contact email)
and `SB_LLM_API_KEY` (the free Google key), granting this notebook access. No
Yahoo, SEC account or database login is needed. Never print credentials or put
them in notebook literals, YAML, Git or command arguments.

This launcher supplies credentials only to the jobs that need them:

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

## Build features

For a new workspace, run each stage explicitly:

```python
research_job(["freeze-universe"], sec=True)
research_job(["capture-market"])
research_job(["collect-sec", "--sec-source", "source_v3"], sec=True)
research_job(["build-registry", "--workers", "2"])
```

Restore exact existing generations instead of repeating these captures when
reproducing the current study. Use the registry's printed `research_version`,
never a directory selected by modification time. Preserve the computational
source while a job runs.

```python
registry_version = input("Exact registered research_version: ").strip()
batch_name = input("Exact restored batch or a new immutable batch name: ").strip()
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

Omit `--download-model` when the pinned assets are cached under
`repository/data/cache/huggingface`. The separate 500-event Gemma schedule leaves
unscheduled/invalid catalysts UNKNOWN; it does not limit SEC/metadata/FinBERT
processing. Text exclusions retain source offsets and raw coverage denominators.
See the [runbook](RESEARCH_V2_RUNBOOK.md) for complete-job, partial-pilot and
checkpoint-recovery rules. A generic invocation does not recreate the special
audited local launch. The Windows launcher is Windows-only, and its checkpoint
audit binds absolute workspace/cache paths. Copying that receipt to Colab does
not authorize partial-batch resumption there; such relocation needs separately
reviewed portable recovery. Completed-workspace restoration is described below.

## Fit, verify and publish

Fit 2006–2019, tune on forward 2018/2019 folds, calibrate on 2020–2021 and assess
on 2022–2023. Full target horizons are purged at boundaries. **2024–2025 outcomes
remain locked**. The primary comparison is calibrated logistic B-both versus A
at 20 sessions; report all predeclared families, ablations and sensitivities.

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

Verify each printed evaluation version without API access:

```python
for horizon in (20, 10, 30):
    model_version = input(f"Exact printed evaluation version for h{horizon}: ").strip()
    research_job(["verify-models", "--model-version", model_version])
```

After the complete three-horizon pipeline passes independent acceptance, publish
its exact operational receipt and bound hosted-CI evidence:

```python
pipeline_receipt = input("Completed verified pipeline receipt path: ").strip()
ci_gate = input("Exact bound hosted-CI receipt path: ").strip()
research_job(["promote-primary", "--pipeline-receipt", pipeline_receipt, "--ci-gate", ci_gate])
```

Publication performs fresh source/native-model replay. An incomplete run or
fixture receipt cannot publish readiness. Restore the exact receipts with the
workspace; do not fabricate them or rewrite manifests. Report negative or
inconclusive results as well as coverage and uncertainty. Forecast improvement
does not establish profitability; the [protocol](RESEARCH_V2_PROTOCOL.md)
discloses the survivor, vendor-snapshot and retrospective-text-model limitations.

## Preserve results and use the app

Colab runtimes are temporary. Once jobs close their database connections, archive
the workspace and download it or copy the archive to Google Drive. Restore into
local `/content` before running again; do not operate an active database directly
on a Drive mount.

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

The workspace archive contains sources, checkpoints and fitted artifacts, but
not the repository's `.venv`, local `.env` or separate FinBERT asset cache.
Reinstall the frozen environment, restore or download pinned assets, and verify
the restored publication before interpreting results.

Colab supports batch computation. Launch the accepted read-only app locally with
`uv run --frozen --extra nlp streamlit run app/streamlit_app.py`; set `SB_WORKSPACE_ROOT` for
a relocated workspace. A source clone alone cannot display actual results. See
the [app guide](../app/README.md) and [status](STATUS.md) for publication readiness.

The [reference archive](archive/README.md) preserves original runbooks and fixture
instructions separately from this workflow. Normal tests use synthetic inputs
with network access blocked:

```python
subprocess.run(
    ["uv", "run", "--frozen", "pytest"],
    cwd=repository,
    check=True,
)
```

References: [uv Python installation](https://docs.astral.sh/uv/guides/install-python/),
[frozen synchronization](https://docs.astral.sh/uv/concepts/projects/sync/),
[Colab Secrets](https://github.com/googlecolab/colabtools/blob/main/google/colab/userdata.py),
[runtime lifecycle](https://research.google.com/colaboratory/faq.html).

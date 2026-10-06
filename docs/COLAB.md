# Run the project in Google Colab

Colab is a launcher for the same Python package and batch commands used locally.
The project runs in its own Python 3.11 `.venv` using the committed `uv.lock`, even
if Colab's host kernel uses a different Python version. Do not copy the Windows
course `.venv` into Colab. No JupyterLab, ipykernel, widget or notebook package is
required by this project.

## 1. Get the source

Open a new Colab notebook. For this private repository, either upload a ZIP downloaded
from GitHub and extract it under `/content`, or clone using the following cell.
Use a short-lived GitHub token with read access to this repository when prompted.
The token is hidden from output, passed only in the clone process environment, and
never placed in the Git remote URL or repository files.

```python
import base64
import getpass
import os
import subprocess

repository = "/content/Project_AI_in_Finance"
token = getpass.getpass("GitHub token (read access to this private repo): ")
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
            "--branch",
            "phase-2-econometrics",
            "https://github.com/MariusPoulsen/Project_AI_in_Finance.git",
            repository,
        ],
        env=clone_env,
        check=True,
    )
finally:
    del token, clone_env
```

The branch above contains the Phase 2 implementation stacked on Phase 1. After the
phase branches are merged, use `main` instead.
For a reproducible research run, check out a reviewed commit or tag explicitly.

## 2. Install and verify the foundation, data and econometric pipelines

Run these Colab cells:

```python
%pip install uv==0.12.20
```

```python
import subprocess
import sys

subprocess.run(
    [
        sys.executable,
        "/content/Project_AI_in_Finance/scripts/colab_bootstrap.py",
        "--workspace-root",
        "/content/structural-break-workspace",
        "--data-fixture",
        "--relationship-fixture",
    ],
    check=True,
)
```

The bootstrap installs Python 3.11 through uv, performs `uv sync --frozen`, validates
configuration, builds the database and runs the offline storage fixture job.
`--data-fixture` also ingests the complete synthetic Phase 1 fixture, replays its
immutable raw sources and verifies the resulting snapshot through the local catalogue.
`--relationship-fixture` independently builds and verifies artificial cointegrated,
independent-walk and stationary-price histories through the actual Phase 2 job.
It does not need the Phase 1 fixture or a provider account. The script prints the
generated snapshot and relationship versions; each run uses fresh identities.
Omit both fixture flags to run only foundation checks. A CPU runtime is sufficient
for Phase 2; Statsmodels and Matplotlib install with the default locked dependencies.
Dependency/Python downloads require internet; fixture jobs do not call data sources
or LLMs.

Subsequent commands use `uv run`, not the host kernel's `import structural_break`:

```python
subprocess.run(
    [
        "uv",
        "run",
        "--frozen",
        "structural-break",
        "storage-smoke",
        "--workspace-root",
        "/content/structural-break-workspace",
    ],
    cwd="/content/Project_AI_in_Finance",
    check=True,
)
```

To run the test suite, use:

```python
subprocess.run(
    ["uv", "run", "--frozen", "pytest"], cwd="/content/Project_AI_in_Finance", check=True
)
```

## 3. Ingest public research data

The data providers and local DuckDB database require no account login. Scripted SEC
requests require a declared project name and real contact email in
`SB_SEC_USER_AGENT`. Add this value to Colab Secrets and grant this notebook access,
or enter it at the hidden prompt below. The value is passed only to the child
process; it is not written to repository files or printed.

```python
import getpass
import os
from uuid import uuid4

try:
    from google.colab import userdata

    sec_identity = userdata.get("SB_SEC_USER_AGENT")
except Exception:
    sec_identity = getpass.getpass("SEC User-Agent (project name and contact email): ")

run_env = os.environ.copy()
run_env["SB_SEC_USER_AGENT"] = sec_identity
snapshot_id = "colab-research-" + uuid4().hex[:12]
try:
    subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "structural-break",
            "ingest-data",
            "--workspace-root",
            "/content/structural-break-research",
            "--snapshot-id",
            snapshot_id,
        ],
        cwd=repository,
        env=run_env,
        check=True,
    )
finally:
    del sec_identity, run_env
print("Research snapshot:", snapshot_id)
```

This downloads the fixed 28-pair universe plus SPY/required sector ETFs for
2014-01-01 through 2025-12-31, official VIX history and SEC submission metadata.
Missing equity prices remain missing; blocking quality checks stop publication.
VIX context uses the exact previous NYSE session. This command does not fit models
or inspect headline final-test metrics. See [the data runbook](DATA_RUNBOOK.md)
for source limitations, source failures and snapshot recovery.

After a successful ingestion, verification and replay run without source access:

```python
replay_id = snapshot_id + "-replay"
for arguments in (
    ["replay-data", "--replay-from", snapshot_id, "--snapshot-id", replay_id],
    ["verify-data"],
):
    subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "structural-break",
            *arguments,
            "--workspace-root",
            "/content/structural-break-research",
        ],
        cwd=repository,
        check=True,
    )
```

Use a fresh replay ID for each new rebuild. Frozen source files and snapshot IDs
are immutable. Subsequent historical queries read the active local snapshot.

## 4. Build relationships from the frozen research data

Once the Phase 1 snapshot is published in `/content/structural-break-research`, the
econometric job uses those local files without new source access or credentials:

```python
for arguments in (
    ["verify-data"],
    ["build-relationships"],
    ["verify-relationships"],
):
    subprocess.run(
        [
            "uv",
            "run",
            "--frozen",
            "structural-break",
            *arguments,
            "--workspace-root",
            "/content/structural-break-research",
        ],
        cwd=repository,
        check=True,
    )
```

The build defaults to the source history from 2014 through 2025. Add
`--start YYYY-MM-DD`, `--end YYYY-MM-DD` or `--relationship-version NAME` to
`build-relationships` when an explicit scope/version is required. Earlier supplied
prices remain available for formation warm-up. Repeating the same registered
identity verifies and returns its existing immutable outputs.

The job writes monthly relationship attempts, frozen daily states and raw fresh
crossings to versioned DuckDB analytics tables plus immutable Parquet artifacts.
It does not create labels, simulate trades or compute final-test outcomes. Inspect
representative diagnostics in synthetic/training/validation periods only; keep
2024–2025 outcome/performance evaluation locked until the methodology is frozen
and the final run is explicitly authorised. See
[the econometrics runbook](ECONOMETRICS_RUNBOOK.md) for the scientific conventions
and local historical query examples.

## 5. Preserve generated research state

Colab virtual machines are temporary. Keep the virtual environment and active
DuckDB database on the local `/content` filesystem. After jobs close their database
connections, archive the workspace and download it or copy the archive to mounted
Google Drive. Restore it to local `/content` before the next session. The stores use
atomic local-file publication and are not intended to operate an active database
directly on a Google Drive mount.

```python
import shutil
from google.colab import files

archive = shutil.make_archive(
    "/content/structural-break-workspace",
    "zip",
    root_dir="/content/structural-break-workspace",
)
files.download(archive)
```

The archive example uses the synthetic fixture workspace. For research ingestion,
archive `/content/structural-break-research` instead. Restore to the same local path
or rebuild the local catalogue from the stored source snapshot using the data
runbook. Never put credentials in YAML or committed notebook cells. Streamlit is a
later-phase deliverable; the bootstrap runs the foundation and optional Phase 1/2
acceptance commands.

References: [uv Python installation](https://docs.astral.sh/uv/guides/install-python/),
[uv frozen synchronization](https://docs.astral.sh/uv/concepts/projects/sync/),
[Colab Secrets API](https://github.com/googlecolab/colabtools/blob/main/google/colab/userdata.py),
[Colab runtime lifecycle](https://research.google.com/colaboratory/faq.html).

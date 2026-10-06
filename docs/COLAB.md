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
            "phase-0-foundation",
            "https://github.com/MariusPoulsen/Project_AI_in_Finance.git",
            repository,
        ],
        env=clone_env,
        check=True,
    )
finally:
    del token, clone_env
```

The branch above contains Phase 0. After it is merged, use `main` instead.
For a reproducible research run, check out a reviewed commit or tag explicitly.

## 2. Install and verify the foundation

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
    ],
    check=True,
)
```

The bootstrap installs Python 3.11 through uv, performs `uv sync --frozen`, validates
configuration, builds the database and runs the offline storage fixture job. A CPU
runtime is sufficient for Phase 0. Dependency/Python downloads require internet;
the foundation jobs do not call data sources or LLMs.

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

## 3. Preserve generated research state

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

Credentials are unnecessary for Phase 0. Later phases can read Colab Secrets and
pass them as `SB_LLM_API_KEY` / `SB_SEC_USER_AGENT` in the child process environment.
Never put them in YAML or committed notebook cells. Streamlit is a later-phase
deliverable; this bootstrap currently runs the research foundation commands.

References: [uv Python installation](https://docs.astral.sh/uv/guides/install-python/),
[uv frozen synchronization](https://docs.astral.sh/uv/concepts/projects/sync/),
[Colab runtime lifecycle](https://research.google.com/colaboratory/faq.html).

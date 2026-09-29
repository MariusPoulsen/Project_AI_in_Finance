"""Launch the locked project from Colab's host Python without replacing its kernel."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("Install uv in the Colab host first: %pip install uv==0.12.20")
    subprocess.run([uv, "python", "install", "3.11"], cwd=root, check=True)
    subprocess.run([uv, "sync", "--frozen", "--python", "3.11"], cwd=root, check=True)
    options = ["--project-root", str(root)]
    if args.workspace_root:
        options += ["--workspace-root", str(args.workspace_root)]
    for command in ("check-config", "init-db", "storage-smoke"):
        subprocess.run(
            [uv, "run", "--frozen", "structural-break", command, *options],
            cwd=root,
            check=True,
        )
    print(f"Foundation verified. Host Python: {sys.version.split()[0]}; project: Python 3.11")


if __name__ == "__main__":
    main()

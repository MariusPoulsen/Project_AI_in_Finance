"""One launcher for collaborator setup, app, prediction and backtest inputs."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def uv_command() -> list[str]:
    executable = shutil.which("uv")
    if executable:
        return [executable]
    if importlib.util.find_spec("uv") is None:
        subprocess.run([sys.executable, "-m", "pip", "install", "uv==0.12.20"], check=True)
    return [sys.executable, "-m", "uv"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "setup",
            "app",
            "research-app",
            "app-bundle",
            "check",
            "predict",
            "backtest-inputs",
            "export",
        ),
    )
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--sha256", help="SHA-256 supplied with the shared snapshot")
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--horizon", type=int, default=20, choices=(20, 10, 30))
    parser.add_argument("--pair")
    parser.add_argument("--primary-version")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    settings_file = root / ".team/workspace.json"
    saved = json.loads(settings_file.read_text(encoding="utf-8")) if settings_file.is_file() else {}
    workspace = args.workspace_root or Path(saved.get("workspace_root", root / "data/team"))
    if not workspace.is_absolute():
        workspace = root / workspace
    workspace = workspace.resolve()
    if args.command == "setup" and (args.snapshot is None or args.sha256 is None):
        parser.error("setup requires --snapshot FILE.zip and the owner's --sha256")
    if args.command == "export" and (args.workspace_root is None or args.output is None):
        parser.error(
            "export requires the owner's accepted --workspace-root and a new --output FILE.zip"
        )
    if args.command == "app-bundle" and args.output is None:
        parser.error("app-bundle requires a new --output directory outside the workspace")
    if args.command == "backtest-inputs" and args.pair is None:
        parser.error("backtest-inputs requires --pair, for example KO__PEP")
    uv = uv_command()
    environment = os.environ.copy()
    # Some Windows cloud-backed files cannot be hardlinked into a new venv.
    environment.setdefault("UV_LINK_MODE", "copy")
    if args.command == "setup":
        subprocess.run([*uv, "python", "install", "3.11"], cwd=root, env=environment, check=True)
        subprocess.run(
            [*uv, "sync", "--frozen", "--python", "3.11"], cwd=root, env=environment, check=True
        )
    run = [*uv, "run", "--frozen"]
    options = ["--project-root", str(root), "--workspace-root", str(workspace)]
    if args.command in {"app", "research-app"}:
        subprocess.run(
            [*run, "structural-break-team", "check", *options],
            cwd=root,
            env=environment,
            check=True,
        )
        environment["SB_WORKSPACE_ROOT"] = str(workspace)
        environment.setdefault("SB_EXPERIMENTS_ROOT", str(root / ".acceptance"))
        script = "app/research_app.py" if args.command == "research-app" else "app/streamlit_app.py"
        return subprocess.run(
            [*run, "python", "-m", "streamlit", "run", script],
            cwd=root,
            env=environment,
        ).returncode
    if args.command == "app-bundle":
        return subprocess.run(
            [
                *run,
                "structural-break-app",
                "export",
                *options,
                "--experiments-root",
                str(root / ".acceptance"),
                "--output",
                str(args.output.resolve()),
            ],
            cwd=root,
            env=environment,
        ).returncode
    command = "import" if args.command == "setup" else args.command
    arguments = [*run, "structural-break-team", command, *options]
    if args.command == "setup":
        arguments += ["--archive", str(args.snapshot.resolve()), "--sha256", args.sha256]
    elif args.command in {"predict", "backtest-inputs"}:
        arguments += ["--horizon", str(args.horizon)]
        if args.pair:
            arguments += ["--pair", args.pair]
    if args.output:
        arguments += ["--output", str(args.output.resolve())]
    if args.primary_version:
        arguments += ["--primary-version", args.primary_version]
    result = subprocess.run(arguments, cwd=root, env=environment)
    if result.returncode == 0 and args.command == "setup":
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(
            json.dumps({"workspace_root": str(workspace)}, indent=2), encoding="utf-8"
        )
        print("Setup complete. Launch the app: python scripts/team.py app")
        print("Check saved-model predictions: python scripts/team.py predict --pair KO__PEP")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

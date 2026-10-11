"""Launch the locked project from Colab's host Python without replacing its kernel."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument(
        "--agents", action="store_true", help="Install locked LangGraph dependencies"
    )
    parser.add_argument(
        "--agent-fixture", action="store_true", help="Verify the offline bounded Phase 5 debate"
    )
    parser.add_argument(
        "--nlp",
        action="store_true",
        help="Install and retain the optional local CPU FinBERT dependencies",
    )
    parser.add_argument(
        "--data-fixture",
        action="store_true",
        help="Also ingest, replay and verify the complete synthetic Phase 1 snapshot offline",
    )
    parser.add_argument(
        "--relationship-fixture",
        action="store_true",
        help="Also build and verify the independent synthetic Phase 2 history offline",
    )
    parser.add_argument(
        "--ml-fixture",
        action="store_true",
        help="Build events, train and reload Model A on offline synthetic history",
    )
    parser.add_argument(
        "--intelligence-fixture",
        action="store_true",
        help="Also build SEC evidence, mock extractions and Model B offline",
    )
    parser.add_argument(
        "--research-fixture",
        action="store_true",
        help="Verify the primary research-v2 pipeline with offline integration fixtures",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("Install uv in the Colab host first: %pip install uv==0.12.20")
    subprocess.run([uv, "python", "install", "3.11"], cwd=root, check=True)
    extras = ["--extra", "nlp"] if args.nlp else []
    if args.agents or args.agent_fixture:
        extras += ["--extra", "agents"]
    subprocess.run([uv, "sync", "--frozen", "--python", "3.11", *extras], cwd=root, check=True)
    run = [uv, "run", "--frozen", *extras]
    options = ["--project-root", str(root)]
    if args.workspace_root:
        options += ["--workspace-root", str(args.workspace_root)]
    for command in ("check-config", "init-db", "storage-smoke"):
        subprocess.run(
            [*run, "structural-break", command, *options],
            cwd=root,
            check=True,
        )
    print(f"Foundation verified. Host Python: {sys.version.split()[0]}; project: Python 3.11")
    if args.agent_fixture:
        agent_root = args.workspace_root or root / ".acceptance/phase5-colab"
        subprocess.run(
            [
                *run,
                "structural-break-agents",
                "--fixture",
                "--mode",
                "mock",
                "--output-dir",
                str(agent_root / "agents"),
            ],
            cwd=root,
            check=True,
        )
        print("Phase 5 synthetic debate and deterministic controller verified; no live API calls")
    if args.data_fixture:
        snapshot = f"colab-fixture-{uuid4().hex[:12]}"
        replay = f"{snapshot}-replay"
        jobs = (
            (
                "ingest-data",
                "--fixture",
                str(root / "tests/fixtures/phase1"),
                "--snapshot-id",
                snapshot,
            ),
            ("replay-data", "--replay-from", snapshot, "--snapshot-id", replay),
            ("verify-data",),
        )
        for job in jobs:
            subprocess.run(
                [*run, "structural-break-reference", *job, *options],
                cwd=root,
                check=True,
            )
        print(f"Phase 1 synthetic snapshot verified: {snapshot}; offline replay: {replay}")
    if args.relationship_fixture:
        relationship_version = f"colab-relationship-fixture-{uuid4().hex[:12]}"
        for relationship_job in (
            (
                "build-relationships",
                "--relationship-fixture",
                "--relationship-version",
                relationship_version,
            ),
            ("verify-relationships",),
        ):
            subprocess.run(
                [*run, "structural-break-reference", *relationship_job, *options],
                cwd=root,
                check=True,
            )
        print(f"Phase 2 synthetic econometric history verified: {relationship_version}")
    if args.ml_fixture or args.intelligence_fixture:
        for model_job in (
            ("build-events", "--ml-fixture"),
            ("train-model-a",),
            ("verify-model-a",),
        ):
            subprocess.run(
                [*run, "structural-break-reference", *model_job, *options],
                cwd=root,
                check=True,
            )
        print("Phase 3 event dataset, trained Model A and saved-bundle reload verified")
    if args.intelligence_fixture:
        for intelligence_job in (
            ("build-intelligence", "--intelligence-fixture"),
            ("verify-intelligence",),
            ("train-model-b",),
            ("verify-model-b",),
        ):
            subprocess.run(
                [*run, "structural-break-reference", *intelligence_job, *options],
                cwd=root,
                check=True,
            )
        print("Phase 4 SEC intelligence and Model B verified with synthetic provider outputs")
    if args.research_fixture:
        subprocess.run(
            [*run, "pytest", "tests/integration/test_research_runner.py", "-q"],
            cwd=root,
            check=True,
        )
        print("Primary research-v2 offline pipeline and native-model integration verified")


if __name__ == "__main__":
    main()

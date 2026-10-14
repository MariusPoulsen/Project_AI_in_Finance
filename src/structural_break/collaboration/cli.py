"""Small offline commands for the group working snapshot."""

from __future__ import annotations

import argparse
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from structural_break.collaboration.queries import (
    backtest_inputs,
    existing_predictions,
    write_frames,
)
from structural_break.collaboration.snapshot import check_snapshot, export_snapshot, import_snapshot
from structural_break.config.paths import ProjectPaths, find_project_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("export", "import", "check", "predict", "backtest-inputs")
    )
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--primary-version")
    parser.add_argument("--horizon", type=int, default=20, choices=(20, 10, 30))
    parser.add_argument("--pair")
    parser.add_argument("--models", nargs="+", default=["logistic_A", "logistic_B_both"])
    args = parser.parse_args(argv)
    root = (args.project_root or find_project_root()).resolve()
    paths = ProjectPaths.resolve(root, args.workspace_root or root / "data/team")
    try:
        if args.command == "import":
            if args.archive is None or args.sha256 is None:
                parser.error("import requires --archive and the owner's --sha256")
            result = import_snapshot(
                root, args.archive, paths.workspace_root, expected_sha256=args.sha256
            )
        elif args.command == "export":
            if args.output is None:
                parser.error("export requires a new --output ZIP filename")
            result = export_snapshot(paths, args.output, primary_version=args.primary_version)
        elif args.command == "check":
            result = check_snapshot(paths)
        else:
            check_snapshot(paths)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            suffix = ".csv" if args.command == "predict" else ""
            output = (
                args.output or root / "outputs" / (args.command + "_" + stamp + suffix)
            ).resolve()
            if output.is_relative_to(paths.workspace_root):
                raise ValueError("Write your own results outside the imported research snapshot")
            if args.command == "predict":
                rows, result = existing_predictions(
                    paths, horizon=args.horizon, pair_id=args.pair, models=tuple(args.models)
                )
                if output.exists():
                    raise FileExistsError("Choose a new prediction filename")
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("x", encoding="utf-8", newline="") as stream:
                    rows.to_csv(stream, index=False)
            else:
                if args.pair is None:
                    parser.error("backtest-inputs requires --pair, for example KO__PEP")
                result = {
                    "pair_id": args.pair,
                    "horizon": args.horizon,
                    "files": write_frames(
                        backtest_inputs(paths, args.pair, horizon=args.horizon), output
                    ),
                    "final_test_unlocked": False,
                }
            result["output"] = str(output)
        print(json.dumps({"status": "SUCCESS", "command": args.command, **result}, default=str))
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        print(json.dumps({"status": "FAILED", "command": args.command, "message": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

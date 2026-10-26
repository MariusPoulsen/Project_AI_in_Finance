"""`structural-break-app`: export, verify or preview presentation bundles.

`export` reads an accepted workspace read-only and writes a new bundle directory
(never into the workspace). `synthetic` writes a clearly labelled invented
preview for development and smoke tests. `verify` re-checks a bundle.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from structural_break.app_bundle.io import read_bundle, write_bundle
from structural_break.app_bundle.strategy import find_experiments
from structural_break.config.paths import ProjectPaths


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="structural-break-app", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Export an accepted workspace to a bundle")
    export.add_argument("--workspace-root", type=Path, required=True)
    export.add_argument("--project-root", type=Path, default=Path.cwd())
    export.add_argument("--primary-version")
    export.add_argument(
        "--experiment",
        type=Path,
        action="append",
        default=[],
        help="A Phase 6 experiment manifest.json (repeat for each horizon)",
    )
    export.add_argument(
        "--experiments-root",
        type=Path,
        help="Directory searched for historical-experiments/*/manifest.json",
    )
    export.add_argument("--showcase-pairs", type=int, default=40)
    export.add_argument("--pair", action="append", default=[], help="Always include this pair")
    export.add_argument("--output", type=Path, required=True)
    synthetic = commands.add_parser("synthetic", help="Write an invented SYNTHETIC PREVIEW bundle")
    synthetic.add_argument("--output", type=Path, required=True)
    synthetic.add_argument("--pairs", type=int, default=36)
    synthetic.add_argument("--seed", type=int, default=5557)
    synthetic.add_argument("--small", action="store_true")
    verify = commands.add_parser("verify", help="Re-verify a bundle and print its identity")
    verify.add_argument("--bundle", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "export":
        from structural_break.app_bundle.workspace import build_from_workspace

        paths = ProjectPaths.resolve(arguments.project_root, arguments.workspace_root)
        if paths.workspace_root in arguments.output.resolve().parents:
            raise SystemExit("Write bundles outside the research workspace")
        experiments = list(arguments.experiment)
        if arguments.experiments_root is not None:
            experiments += find_experiments(arguments.experiments_root)
        bundle = build_from_workspace(
            paths,
            primary_version=arguments.primary_version,
            experiments=experiments,
            showcase=arguments.showcase_pairs,
            required_pairs=arguments.pair,
            lazy_pairs=False,
            source="bundle",
        )
        manifest = write_bundle(bundle, arguments.output)
    elif arguments.command == "synthetic":
        from structural_break.app_bundle.synthetic import synthetic_bundle

        bundle = synthetic_bundle(pairs=arguments.pairs, seed=arguments.seed, small=arguments.small)
        manifest = write_bundle(bundle, arguments.output)
    else:
        manifest = arguments.bundle / "bundle.json"
    checked = read_bundle(manifest.parent)
    size = sum(path.stat().st_size for path in manifest.parent.rglob("*") if path.is_file())
    print(
        json.dumps(
            {
                "bundle": str(manifest.parent),
                "bundle_id": checked.identity.bundle_id,
                "synthetic": checked.identity.synthetic,
                "primary_version": checked.identity.primary_version,
                "horizons": sorted(checked.horizons),
                "experiments": checked.identity.experiments,
                "showcase_pairs": len(checked.identity.showcase_pairs),
                "size_mb": round(size / 1e6, 2),
                "final_test_read": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Primary research-v2 commands, with shared infrastructure in its workspace."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from structural_break.config.loader import config_hash, load_config
from structural_break.config.models import RuntimeSettings
from structural_break.config.paths import ProjectPaths, find_project_root
from structural_break.research import cli as research_cli
from structural_break.research.protocol import identity, load_protocol
from structural_break.services import foundation

_INFRASTRUCTURE_COMMANDS = ("check-config", "init-db", "migrate-db", "storage-smoke")


def main(argv: Sequence[str] | None = None) -> int:
    """V1 reproduction is explicit via ``structural-break-reference``."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    command_parser = argparse.ArgumentParser(add_help=False)
    command_parser.add_argument("command", nargs="?")
    command_parser.add_argument("--project-root", type=Path)
    command_parser.add_argument("--workspace-root", type=Path)
    command, _ = command_parser.parse_known_args(arguments)
    if command.command not in _INFRASTRUCTURE_COMMANDS:
        return research_cli.main(arguments)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=_INFRASTRUCTURE_COMMANDS)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    args = parser.parse_args(arguments)
    try:
        project = find_project_root(args.project_root)
        runtime = RuntimeSettings(_env_file=project / ".env")
        paths = ProjectPaths.resolve(
            project, args.workspace_root or runtime.workspace_root or project / "data/research_v2"
        )
        if paths.workspace_root == project:
            raise ValueError("Primary research requires its own workspace")
        protocol = load_protocol(project / "configs/research_v2.yaml")
        if args.command == "check-config":
            print(
                json.dumps(
                    {
                        "status": "VALID",
                        "research_version": "v2",
                        "protocol_hash": identity(protocol.model_dump(mode="json")),
                        "config_hash": config_hash(load_config(project / "configs")),
                        "workspace_root": str(paths.workspace_root),
                        "final_test_locked": True,
                    },
                    sort_keys=True,
                )
            )
            return 0
        return foundation.main(
            [
                args.command,
                "--project-root",
                str(project),
                "--workspace-root",
                str(paths.workspace_root),
            ]
        )
    except Exception as error:
        print(json.dumps({"status": "FAILED", "error_type": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

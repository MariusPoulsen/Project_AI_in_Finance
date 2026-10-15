"""Resolve content-bound research parents, never the newest directory."""

import json
from pathlib import Path

from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.storage.files import sha256_file


def sec_source_directory(paths: ProjectPaths, intelligence_directory: Path) -> Path:
    manifest = json.loads((intelligence_directory / "manifest.json").read_bytes())
    expected = manifest["inputs"]["sec_manifest_sha256"]
    candidates = []
    for filename in (paths.workspace_root / "sec_metadata").glob("*/manifest.json"):
        checked = confined_path(
            paths.workspace_root, filename.relative_to(paths.workspace_root).as_posix()
        )
        if sha256_file(checked) == expected:
            candidates.append(checked.parent)
    if len(candidates) != 1:
        raise ValueError("Intelligence must bind one unambiguous SEC metadata snapshot")
    return candidates[0]

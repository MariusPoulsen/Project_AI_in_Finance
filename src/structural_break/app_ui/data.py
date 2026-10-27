"""Locate and load the application's verified data, cached by identity.

Order: an explicit `SB_APP_BUNDLE`, then a committed demo bundle at
`demo/app_bundle`, then the accepted workspace (`SB_WORKSPACE_ROOT` or
`data/research_v2`) read in memory with any Phase 6 experiments found under
`SB_EXPERIMENTS_ROOT` (default `.acceptance`). Loading never writes anything.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import streamlit as st

from structural_break.app_bundle.contracts import AppBundle
from structural_break.app_bundle.io import read_bundle
from structural_break.app_bundle.strategy import find_experiments
from structural_break.config.models import RuntimeSettings
from structural_break.config.paths import ProjectPaths
from structural_break.research.primary import PrimaryNotReadyError, primary_versions
from structural_break.services.research_application import ResearchApplicationService
from structural_break.services.research_summary import (
    ResearchSummaryService,
    artifact_identity,
    read_summary,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class DataSource:
    kind: Literal["bundle", "workspace"]
    location: Path


@dataclass(frozen=True)
class LoadOutcome:
    status: Literal["ready", "pending", "failed"]
    service: ResearchApplicationService | None = None
    message: str = ""


@dataclass(frozen=True)
class SummaryOutcome:
    status: Literal["ready", "pending", "failed"]
    service: ResearchSummaryService | None = None
    message: str = ""


@st.cache_resource(show_spinner=False, max_entries=2)
def _summary(location: str, identity: tuple[str, ...]) -> ResearchSummaryService:
    del identity
    return read_summary(Path(location))


def load_summary(root: Path = PROJECT_ROOT) -> SummaryOutcome:
    explicit = Path(os.environ.get("SB_RESEARCH_SUMMARY", "demo/book"))
    folder = explicit if explicit.is_absolute() else root / explicit
    try:
        identity = artifact_identity(folder)
        return SummaryOutcome("ready", _summary(str(folder.resolve()), identity))
    except FileNotFoundError:
        return SummaryOutcome(
            "pending",
            message="The current research presentation snapshot "
            "is not available. Ask the project owner for the demo/book export.",
        )
    except Exception:  # noqa: BLE001 - fail closed without exposing paths or internals
        return SummaryOutcome(
            "failed",
            message="The current presentation files do not match "
            "their manifest or data contract. Results are withheld. Ask the "
            "project owner to verify and re-export the presentation snapshot.",
        )


def resolve_source(root: Path = PROJECT_ROOT) -> DataSource:
    explicit = os.environ.get("SB_APP_BUNDLE")
    if explicit:
        path = Path(explicit)
        return DataSource("bundle", path if path.is_absolute() else root / path)
    demo = root / "demo" / "app_bundle"
    if (demo / "bundle.json").is_file():
        return DataSource("bundle", demo)
    runtime = RuntimeSettings(_env_file=root / ".env")
    workspace = runtime.workspace_root or root / "data/research_v2"
    return DataSource("workspace", Path(workspace))


@st.cache_resource(show_spinner=False, max_entries=2)
def _bundle(location: str, digest: str) -> AppBundle:
    del digest  # part of the cache key: a changed manifest is a different bundle
    return read_bundle(Path(location))


@st.cache_resource(show_spinner=False, max_entries=2)
def _workspace(
    root: str, workspace: str, versions: tuple[str, ...], experiments: tuple[str, ...]
) -> AppBundle:
    from structural_break.app_bundle.workspace import build_from_workspace

    del versions  # cache key: a newly published primary is a different view
    paths = ProjectPaths.resolve(Path(root), Path(workspace))
    return build_from_workspace(
        paths, experiments=[Path(p) for p in experiments], skip_unmatched_experiments=True
    )


def load(source: DataSource, root: Path = PROJECT_ROOT) -> LoadOutcome:
    try:
        if source.kind == "bundle":
            manifest = source.location / "bundle.json"
            if not manifest.is_file():
                return LoadOutcome(
                    "pending",
                    message=f"No app bundle was found at {source.location}. Export one with "
                    "`structural-break-app export` or unset SB_APP_BUNDLE.",
                )
            digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
            bundle = _bundle(str(source.location.resolve()), digest)
        else:
            paths = ProjectPaths.resolve(root, source.location)
            versions = primary_versions(paths) if paths.database.exists() else ()
            if not versions:
                return LoadOutcome(
                    "pending",
                    message="No accepted research generation is available in this workspace yet. "
                    "Import the group snapshot with `python scripts/team.py setup`, or point "
                    "SB_APP_BUNDLE at an exported app bundle.",
                )
            experiments_root = Path(os.environ.get("SB_EXPERIMENTS_ROOT", root / ".acceptance"))
            experiments = tuple(str(p) for p in find_experiments(experiments_root))
            bundle = _workspace(str(root), str(paths.workspace_root), tuple(versions), experiments)
    except PrimaryNotReadyError:
        return LoadOutcome(
            "pending",
            message="The accepted research generation is not published yet, so there is nothing "
            "to display. Results appear here once all three evaluations pass verification.",
        )
    except Exception:  # noqa: BLE001 - never show internals; fail closed
        return LoadOutcome(
            "failed",
            message="The research outputs failed verification and are not shown. Re-run "
            "`python scripts/team.py check` (or `structural-break-app verify`) to find the file.",
        )
    return LoadOutcome("ready", ResearchApplicationService(bundle))

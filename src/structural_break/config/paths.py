"""Resolve canonical storage paths independently of the current working directory."""

from dataclasses import dataclass
from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    candidate = (start or Path.cwd()).resolve()
    for root in (candidate, *candidate.parents):
        if (root / "pyproject.toml").is_file() and (root / "configs").is_dir():
            return root
    raise FileNotFoundError("Project root not found; pass --project-root explicitly")


def confined_path(root: Path, relative: str | Path) -> Path:
    text = str(relative)
    if "\\" in text or ":" in text or ".." in Path(text).parts:
        raise ValueError("Use a portable relative path without traversal")
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("Path escapes the configured storage root")
    if path == root.resolve():
        raise ValueError("A file or subdirectory name is required")
    return path


@dataclass(frozen=True)
class ProjectPaths:
    project_root: Path
    workspace_root: Path

    @classmethod
    def resolve(
        cls, project_root: Path, workspace_root: str | Path | None = None
    ) -> "ProjectPaths":
        project = project_root.resolve()
        workspace = Path(workspace_root) if workspace_root is not None else project
        if not workspace.is_absolute():
            workspace = project / workspace
        return cls(project, workspace.resolve())

    @property
    def data(self) -> Path:
        return self.workspace_root / "data"

    @property
    def artifacts(self) -> Path:
        return self.workspace_root / "artifacts"

    @property
    def database(self) -> Path:
        return self.data / "analytics" / "structural_break.duckdb"

    @property
    def migrations(self) -> Path:
        return self.project_root / "sql"

    def data_path(self, relative: str | Path) -> Path:
        return confined_path(self.data, relative)

    def create_directories(self) -> None:
        for relative in (
            "reference",
            "raw/yahoo/prices",
            "raw/yahoo/actions",
            "raw/cboe/vix",
            "raw/sec/company_tickers",
            "raw/sec/submissions",
            "raw/sec/filings",
            "raw/gdelt",
            "curated/market",
            "curated/evidence",
            "analytics",
            "snapshots",
            "cache/dashboard",
            "cache/agent_runs",
            "demo",
        ):
            self.data_path(relative).mkdir(parents=True, exist_ok=True)
        for relative in ("models", "calibrators", "shap", "manifests", "reports", "mlflow"):
            confined_path(self.artifacts, relative).mkdir(parents=True, exist_ok=True)

from pathlib import Path

import pytest

from structural_break.config.loader import load_config
from structural_break.config.models import ProjectConfig
from structural_break.config.paths import ProjectPaths


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def config(project_root: Path) -> ProjectConfig:
    return load_config(project_root / "configs")


@pytest.fixture
def paths(project_root: Path, tmp_path: Path) -> ProjectPaths:
    return ProjectPaths.resolve(project_root, tmp_path / "workspace")

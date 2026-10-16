import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from structural_break.config.loader import load_config
from structural_break.config.models import ProjectConfig
from structural_break.config.paths import ProjectPaths


@pytest.fixture
def preserve_main_module() -> Iterator[None]:
    # AppTest installs its generated app as __main__ and leaves it there.
    # Restore the pytest entry point so later spawned workers do not re-run
    # a temporary app script without AppTest's injected arguments.
    original = sys.modules["__main__"]
    try:
        yield
    finally:
        sys.modules["__main__"] = original


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def config(project_root: Path) -> ProjectConfig:
    return load_config(project_root / "configs")


@pytest.fixture
def paths(project_root: Path, tmp_path: Path) -> ProjectPaths:
    return ProjectPaths.resolve(project_root, tmp_path / "workspace")

"""Primary routing cannot silently return to the small reference experiment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from structural_break import cli
from structural_break.config.models import RuntimeSettings

PROJECT = Path(__file__).resolve().parents[2]


def settings(workspace: Path | None = None) -> RuntimeSettings:
    return RuntimeSettings(_env_file=None, workspace_root=str(workspace) if workspace else None)


def test_primary_model_commands_dispatch_to_v2_without_legacy_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.research_cli, "main", lambda arguments: calls.append(arguments) or 0)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Primary fitting must never dispatch to reference-v1 jobs")

    monkeypatch.setattr(cli.foundation, "main", forbidden)
    args = ["train-models", "--registry-version", "explicit-version", "--horizon", "20"]
    assert cli.main(args) == 0
    assert calls == [args]


def test_shared_database_initialization_defaults_to_primary_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(cli, "RuntimeSettings", lambda **kwargs: settings())
    monkeypatch.setattr(cli.foundation, "main", lambda arguments: calls.append(arguments) or 0)
    assert cli.main(["init-db", "--project-root", str(PROJECT)]) == 0
    assert calls == [
        [
            "init-db",
            "--project-root",
            str(PROJECT),
            "--workspace-root",
            str(PROJECT / "data/research_v2"),
        ]
    ]


def test_shared_commands_honor_runtime_and_explicit_workspace_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured, explicit = tmp_path / "configured", tmp_path / "explicit"
    configured.mkdir()
    calls: list[list[str]] = []
    monkeypatch.setattr(cli, "RuntimeSettings", lambda **kwargs: settings(configured))
    monkeypatch.setattr(cli.foundation, "main", lambda arguments: calls.append(arguments) or 0)
    assert cli.main(["storage-smoke", "--project-root", str(PROJECT)]) == 0
    assert calls[-1][-1] == str(configured)
    assert (
        cli.main(["migrate-db", "--project-root", str(PROJECT), "--workspace-root", str(explicit)])
        == 0
    )
    assert calls[-1][-1] == str(explicit)


def test_primary_config_reports_frozen_v2_protocol_and_final_lock(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "RuntimeSettings", lambda **kwargs: settings())
    assert cli.main(["check-config", "--project-root", str(PROJECT)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "VALID" and result["research_version"] == "v2"
    assert result["final_test_locked"] is True
    assert result["workspace_root"] == str(PROJECT / "data/research_v2")
    assert len(result["protocol_hash"]) == 64


def test_primary_infrastructure_cannot_overwrite_reference_workspace(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "RuntimeSettings", lambda **kwargs: settings())

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Reference workspace rejection must precede writes")

    monkeypatch.setattr(cli.foundation, "main", forbidden)
    assert cli.main(["init-db", "--workspace-root", str(PROJECT)]) == 1
    assert json.loads(capsys.readouterr().err)["error_type"] == "ValueError"


def test_research_commands_honor_workspace_environment_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from structural_break.research import cli as research

    observed: list[Path] = []
    monkeypatch.setattr(research, "RuntimeSettings", lambda **kwargs: settings(tmp_path))
    monkeypatch.setattr(
        research,
        "run_command",
        lambda args, paths, runtime: observed.append(paths.workspace_root) or {},
    )
    assert research.main(["build-registry", "--project-root", str(PROJECT)]) == 0
    assert observed == [tmp_path]


def test_primary_promotion_requires_explicit_completion_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from structural_break.config.paths import ProjectPaths
    from structural_break.research import cli as research

    args = research._parser().parse_args(["promote-primary"])
    with pytest.raises(ValueError, match="explicit --pipeline-receipt"):
        research.run_command(args, ProjectPaths(PROJECT, PROJECT / "data/research_v2"), settings())

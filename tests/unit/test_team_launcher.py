"""The group launcher selects its locked runtime and the imported workspace."""

import json
from types import SimpleNamespace

import pytest

from scripts import team


def test_setup_remembers_workspace_only_after_success(tmp_path, monkeypatch):
    monkeypatch.delenv("UV_LINK_MODE", raising=False)
    monkeypatch.setattr(team, "__file__", str(tmp_path / "scripts/team.py"))
    monkeypatch.setattr(team, "uv_command", lambda: ["uv"])
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(team.subprocess, "run", run)
    snapshot = tmp_path / "shared with spaces.zip"
    assert team.main(["setup", "--snapshot", str(snapshot), "--sha256", "a" * 64]) == 0
    assert calls[0][0] == ["uv", "python", "install", "3.11"]
    assert calls[1][0] == ["uv", "sync", "--frozen", "--python", "3.11"]
    assert all(kwargs["env"]["UV_LINK_MODE"] == "copy" for _, kwargs in calls)
    assert calls[2][0][-4:] == ["--archive", str(snapshot), "--sha256", "a" * 64]
    assert json.loads((tmp_path / ".team/workspace.json").read_text())["workspace_root"] == str(
        tmp_path / "data/team"
    )
    (tmp_path / ".team/workspace.json").unlink()
    monkeypatch.setattr(
        team.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1)
    )
    assert team.main(["setup", "--snapshot", str(snapshot), "--sha256", "a" * 64]) == 1
    assert not (tmp_path / ".team/workspace.json").exists()


def test_app_checks_snapshot_then_uses_saved_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(team, "__file__", str(tmp_path / "scripts/team.py"))
    monkeypatch.setattr(team, "uv_command", lambda: ["uv"])
    (tmp_path / ".team").mkdir()
    workspace = tmp_path / "colleague Ø"
    (tmp_path / ".team/workspace.json").write_text(json.dumps({"workspace_root": str(workspace)}))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(team.subprocess, "run", run)
    assert team.main(["app"]) == 0
    assert calls[0][0][3:5] == ["structural-break-team", "check"]
    assert calls[0][1]["check"] is True
    assert calls[1][0][3:] == ["python", "-m", "streamlit", "run", "app/streamlit_app.py"]
    assert calls[1][1]["env"]["SB_WORKSPACE_ROOT"] == str(workspace)


def test_research_app_and_bundle_export_use_the_saved_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(team, "__file__", str(tmp_path / "scripts/team.py"))
    monkeypatch.setattr(team, "uv_command", lambda: ["uv"])
    (tmp_path / ".team").mkdir()
    workspace = tmp_path / "workspace"
    (tmp_path / ".team/workspace.json").write_text(json.dumps({"workspace_root": str(workspace)}))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(team.subprocess, "run", run)
    assert team.main(["research-app"]) == 0
    assert calls[0][0][3:5] == ["structural-break-team", "check"]
    assert calls[1][0][3:] == ["python", "-m", "streamlit", "run", "app/research_app.py"]
    assert calls[1][1]["env"]["SB_WORKSPACE_ROOT"] == str(workspace)
    calls.clear()
    assert team.main(["app-bundle", "--output", str(tmp_path / "bundle")]) == 0
    command = calls[0][0]
    assert command[3:5] == ["structural-break-app", "export"]
    assert command[command.index("--workspace-root") + 1] == str(workspace)
    assert command[-1] == str((tmp_path / "bundle").resolve())
    with pytest.raises(SystemExit):
        team.main(["app-bundle"])


def test_missing_setup_inputs_fail_before_runtime_install(monkeypatch):
    monkeypatch.setattr(team, "uv_command", lambda: pytest.fail("Unexpected runtime install"))
    with pytest.raises(SystemExit) as error:
        team.main(["setup"])
    assert error.value.code == 2

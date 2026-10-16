"""Operational status cannot change or silently restart scientific work."""

import json
from pathlib import Path

import pytest

from structural_break.research import cli


def test_progress_keeps_verified_checkpoint_count_during_prefix_loading(tmp_path: Path) -> None:
    path = tmp_path / "progress.json"
    progress = cli._FileProgress(path, "build-intelligence", "fixture")
    progress({"stage": "CHECKPOINT_AUDIT_APPLIED", "completed_checkpoint_count": 2290})
    progress({"stage": "EVENT_INTELLIGENCE", "completed": 1, "total": 37421})
    state = json.loads(path.read_bytes())
    assert state["completed_checkpoint_count"] == 2290
    assert state["completed"] == 1
    assert state["status"] == "RUNNING"
    assert state["final_test_unlocked"] is False
    progress({"status": "FAILED", "error_type": "ValueError"})
    assert json.loads(path.read_bytes())["status"] == "FAILED"


def test_status_file_lock_does_not_abort_canonical_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "progress.json"
    progress = cli._FileProgress(path, "build-intelligence", "fixture")

    def locked(*args: object, **kwargs: object) -> None:
        raise PermissionError("Synthetic lock")

    monkeypatch.setattr(Path, "replace", locked)
    progress({"stage": "EVENT_INTELLIGENCE", "completed": 4, "total": 10})
    assert json.loads(path.read_bytes())["status"] == "STARTING"
    output = capsys.readouterr()
    assert '"completed": 4' in output.out
    assert "PROGRESS_WRITE_FAILED" in output.err
    assert "Synthetic lock" not in output.err


def test_progress_cannot_overwrite_previous_attempt(tmp_path: Path) -> None:
    path = tmp_path / "progress.json"
    path.write_text("preserved")
    with pytest.raises(ValueError, match="new progress file"):
        cli._FileProgress(path, "build-intelligence", "fixture")
    assert path.read_text() == "preserved"


def test_source_progress_is_separate_from_completed_feature_checkpoints(tmp_path: Path) -> None:
    path = tmp_path / "progress.json"
    progress = cli._FileProgress(path, "train-models", "fixture")
    progress(
        {
            "status": "RUNNING",
            "stage": "SOURCE_EVENT_REPLAY",
            "verified_source_events": 100,
            "total_source_events": 37421,
            "parsing_workers": 2,
        }
    )
    state = json.loads(path.read_bytes())
    assert state["verified_source_events"] == 100
    assert state["total_source_events"] == 37421
    assert state["completed_checkpoint_count"] == 0
    assert state["status"] == "RUNNING" and state["final_test_unlocked"] is False


def test_separate_replay_passes_are_counted_without_claiming_job_completion(tmp_path: Path) -> None:
    path = tmp_path / "progress.json"
    progress = cli._FileProgress(path, "train-models", "fixture")
    progress({"stage": "SOURCE_INPUT_BINDINGS", "verified_source_events": 0})
    progress({"stage": "SOURCE_EVENT_REPLAY", "verified_source_events": 37421})
    progress({"stage": "MODEL_FITTING"})
    progress({"stage": "SOURCE_INPUT_BINDINGS", "verified_source_events": 0})
    state = json.loads(path.read_bytes())
    assert state["source_replay_pass_in_command"] == state["source_replay_passes_in_command"] == 2
    assert state["verified_source_events"] == 0
    assert state["completed_checkpoint_count"] == 0
    assert state["final_test_unlocked"] is False


def test_parallel_parsing_cannot_dispatch_feature_capture(tmp_path: Path) -> None:
    from structural_break.config.models import RuntimeSettings
    from structural_break.config.paths import ProjectPaths

    args = cli._parser().parse_args(["build-intelligence", "--parsing-workers", "2"])
    with pytest.raises(ValueError, match="restricted"):
        cli.run_command(
            args, ProjectPaths(Path(__file__).parents[2], tmp_path), RuntimeSettings(_env_file=None)
        )


@pytest.mark.parametrize(
    "arguments",
    [
        ["audit-checkpoints"],
        ["build-intelligence", "--audit-output", "fixture.json"],
        ["build-intelligence", "--progress-file", "data/research_v2/manifest.json"],
    ],
)
def test_invalid_operational_arguments_do_not_dispatch(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("A batch must not run")

    monkeypatch.setattr(cli, "run_command", forbidden)
    assert cli.main(arguments) == 1

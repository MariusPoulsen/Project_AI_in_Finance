"""CLI pause/resume, durable budget and review export without any network calls."""

import json
import sys

import pytest

from structural_break.agents.cli import main


def invoke(monkeypatch, capsys, *arguments):
    monkeypatch.setattr(sys, "argv", ["structural-break-agents", *map(str, arguments)])
    main()
    return json.loads(capsys.readouterr().out)


def test_cli_resume_preserves_all_rows_and_completed_provider_calls(tmp_path, monkeypatch, capsys):
    args = ("batch", "--fixture", "--output-dir", tmp_path / "batch")
    first = invoke(monkeypatch, capsys, *args, "--max-events", "2")
    assert first["completed_count"] == 2
    assert first["complete"] is False and first["manifest_path"] is None
    resumed = invoke(monkeypatch, capsys, *args)
    assert resumed["complete"] and resumed["completed_count"] == resumed["total_count"] == 4
    assert first["new_provider_calls"] + resumed["new_provider_calls"] == 6
    replay = invoke(monkeypatch, capsys, *args)
    assert replay["new_provider_calls"] == 0
    assert replay["batch_id"] == resumed["batch_id"]
    exported = invoke(
        monkeypatch,
        capsys,
        "review-export",
        "--bundle",
        tmp_path / "batch/prepared/manifest.json",
        "--count",
        "4",
        "--output-dir",
        tmp_path / "review",
    )
    assert exported["mode"] == "mock"
    with pytest.raises(ValueError):
        invoke(
            monkeypatch,
            capsys,
            "review-validate",
            "--bundle",
            tmp_path / "batch/prepared/manifest.json",
            "--review-dir",
            tmp_path / "review",
            "--annotations",
            tmp_path / "review/annotations.blank.json",
        )


def test_cli_budget_zero_abstains_without_losing_denominators(tmp_path, monkeypatch, capsys):
    args = ("batch", "--fixture", "--output-dir", tmp_path, "--call-budget", "0")
    result = invoke(monkeypatch, capsys, *args)
    assert result["complete"] and result["completed_count"] == 4
    assert result["new_provider_calls"] == 0
    assert result["disposition_counts"]["BUDGET_EXHAUSTED"] == 1
    assert result["status_counts"]["ABSTAIN"] >= 1
    replay = invoke(monkeypatch, capsys, *args)
    assert replay["new_provider_calls"] == 0
    with pytest.raises(ValueError, match="budget policy"):
        invoke(monkeypatch, capsys, "batch", "--fixture", "--output-dir", tmp_path)


def test_cli_frozen_selection_cap_retains_unscheduled_row(tmp_path, monkeypatch, capsys):
    result = invoke(
        monkeypatch,
        capsys,
        "batch",
        "--fixture",
        "--output-dir",
        tmp_path,
        "--max-investigations",
        "0",
    )
    assert result["complete"] and result["selected_count"] == 0
    assert result["new_provider_calls"] == 0
    assert result["disposition_counts"]["NOT_SCHEDULED"] == 1

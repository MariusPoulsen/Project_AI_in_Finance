"""Real-adapter commands refuse unavailable generations without writing them."""

import sys
from pathlib import Path

import pytest

from structural_break.agents import cli


@pytest.mark.parametrize("command", ["historical-review-export", "historical-input-export"])
def test_unavailable_registered_inputs_cannot_create_an_accepted_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    workspace = tmp_path / "missing-research"
    output = tmp_path / "output"
    args = [
        "agents",
        command,
        "--research-workspace",
        str(workspace),
        "--sec-directory",
        str(tmp_path / "source_v3"),
        "--sec-manifest-sha256",
        "0" * 64,
        "--cache-workspace",
        str(tmp_path / "cache"),
        "--output-dir",
        str(output),
    ]
    if command == "historical-input-export":
        args.extend(["--primary-version", "missing-primary", "--event-id", "not-registered"])
    else:
        args.extend(["--registry-version", "missing-registry"])
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises((FileNotFoundError, RuntimeError, ValueError)):
        cli.main()
    assert not output.exists()
    assert not workspace.exists()

"""No-network batch plumbing, source identity, outcome-free metadata and Colab extras."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import SecretStr

from scripts import colab_bootstrap
from structural_break.config.models import RuntimeSettings
from structural_break.config.paths import ProjectPaths
from structural_break.research import cli
from structural_break.research.protocol import load_protocol

PROJECT = Path(__file__).resolve().parents[2]


def runtime() -> RuntimeSettings:
    return RuntimeSettings(
        _env_file=None,
        llm_api_key=SecretStr("synthetic-secret-never-log"),
        sec_user_agent=SecretStr("Test research contact@example.com"),
    )


def registered_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, timestamp: str | None = None
) -> tuple[ProjectPaths, str, dict[str, Any]]:
    paths = ProjectPaths(PROJECT, tmp_path)
    version = "research_registry_fixture"
    protocol = load_protocol(PROJECT / "configs/research_v2.yaml")
    directory = paths.artifacts / "research" / version
    directory.mkdir(parents=True)
    files = []
    for horizon in (protocol.primary_horizon, *protocol.sensitivity_horizons):
        frame = pd.DataFrame(
            {
                "pair_id": ["KO__PEP", "HD__LOW"],
                "event_timestamp": [
                    timestamp or "2022-03-01T21:00:00+00:00",
                    f"2022-06-{horizon:02d}T20:00:00+00:00",
                ],
                "event_id": [f"h{horizon}_shared", f"h{horizon}_new"],
                "y_revert_success": [1, 0],
                "resolution_date": ["2022-03-04", "2022-07-01"],
                "calibrated_probability": [0.99, 0.01],
            }
        )
        name = f"h{horizon}_events"
        path = directory / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        files.append(
            {
                "name": name,
                "path": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    parent = {
        "stage": "registry",
        "protocol": protocol.model_dump(mode="json"),
        "files": files,
        "inputs": [{"role": "market", "sha256": "d" * 64}],
    }
    monkeypatch.setattr(cli, "_registered_manifest", lambda paths, version: parent)
    return paths, version, parent


def test_union_uses_only_allowlisted_metadata_and_reuses_horizon_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, version, parent = registered_events(tmp_path, monkeypatch)
    read_columns: list[list[str]] = []
    original = pd.read_parquet

    def read(*args: Any, **kwargs: Any) -> pd.DataFrame:
        read_columns.append(kwargs["columns"])
        return original(*args, **kwargs)

    monkeypatch.setattr(cli.pd, "read_parquet", read)
    events, actual_parent, _ = cli.evidence_events(paths, version)
    assert actual_parent == parent
    assert read_columns == [["pair_id", "event_timestamp"]] * 3
    assert len(events) == 4
    assert events["event_id"].is_unique
    assert set(events) == {"event_id", "pair_id", "event_timestamp", "evidence_cutoff"}
    assert len(events.loc[events["pair_id"].eq("KO__PEP")]) == 1
    assert events["event_timestamp"].equals(events["evidence_cutoff"])


def test_target_and_episode_changes_do_not_change_evidence_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, version, parent = registered_events(tmp_path, monkeypatch)
    first, _, _ = cli.evidence_events(paths, version)
    directory = paths.artifacts / "research" / version
    for item in parent["files"]:
        path = directory / item["path"]
        frame = pd.read_parquet(path)
        frame["event_id"] = "new_" + frame["event_id"]
        frame["y_revert_success"] = 1 - frame["y_revert_success"]
        frame["calibrated_probability"] = 0.4
        frame.to_parquet(path, index=False)
        item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    second, _, _ = cli.evidence_events(paths, version)
    pd.testing.assert_frame_equal(first, second)


@pytest.mark.parametrize(
    "timestamp",
    ["2024-01-01T21:00:00+00:00", "2023-12-31T23:00:00-05:00", "2022-03-01T21:00:00"],
)
def test_future_or_naive_metadata_is_blocking_before_any_nlp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timestamp: str
) -> None:
    paths, version, _ = registered_events(tmp_path, monkeypatch, timestamp=timestamp)
    with pytest.raises(ValueError, match="timezone-aware|development history"):
        cli.evidence_events(paths, version)


def test_registry_bytes_and_registration_are_verified_before_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, version, parent = registered_events(tmp_path, monkeypatch)
    path = paths.artifacts / "research" / version / parent["files"][0]["path"]
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        cli.evidence_events(paths, version)
    monkeypatch.setattr(cli, "_registered_manifest", lambda paths, version: None)
    with pytest.raises(ValueError, match="registered"):
        cli.evidence_events(paths, version)


@pytest.mark.parametrize(
    "command", ["freeze-universe", "capture-market", "collect-sec", "build-registry"]
)
def test_source_and_registry_dispatch_are_explicit_separate_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    args = cli._parser().parse_args([command])
    paths = ProjectPaths(PROJECT, tmp_path)
    called: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    source = tmp_path / "sec.json"
    source.write_bytes(b"{}")
    args.sec_directory = source

    def record(name: str) -> Any:
        def call(*values: Any, **options: Any) -> dict[str, Any]:
            called.append((name, values, options))
            return {"job": name}

        return call

    for name in (
        "freeze_universe",
        "collect_market",
        "collect_sec_metadata",
        "build_research_registry",
    ):
        monkeypatch.setattr(cli, name, record(name))
    result = cli.run_command(args, paths, runtime())
    expected = {
        "freeze-universe": "freeze_universe",
        "capture-market": "collect_market",
        "collect-sec": "collect_sec_metadata",
        "build-registry": "build_research_registry",
    }[command]
    assert result == {"job": expected}
    assert len(called) == 1
    values = called[0][1]
    assert any(isinstance(value, Path) and value.is_relative_to(tmp_path) for value in values)
    if command in {"capture-market", "collect-sec"}:
        assert values[3].year == 2023


def test_intelligence_dispatch_never_passes_targets_and_retains_free_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, version, _ = registered_events(tmp_path, monkeypatch)
    args = cli._parser().parse_args(
        ["build-intelligence", "--registry-version", version, "--max-events", "3", "--offline"]
    )
    captured: dict[str, Any] = {}

    def build(events: pd.DataFrame, *sources: Any, **options: Any) -> dict[str, Any]:
        captured.update(events=events, sources=sources, options=options)
        return {"event_count": len(events)}

    monkeypatch.setattr(cli, "build_event_intelligence", build)
    result = cli.run_command(args, paths, runtime())
    assert result["event_count"] == 4
    assert set(captured["events"]) == {"event_id", "pair_id", "event_timestamp", "evidence_cutoff"}
    options = captured["options"]
    assert options["provider"].max_calls == 1000
    assert options["provider"].min_interval_seconds == 8
    assert options["provider"]._credential() == "synthetic-secret-never-log"
    assert options["provider"].model_name.startswith("gemma-")
    assert options["sentiment_backend"].device == "cpu"
    assert options["sentiment_backend"].local_files_only is True
    assert options["max_events"] == 3
    assert options["max_retries"] == 1
    assert options["cache_workspace"] == paths.workspace_root / "cache"
    assert options["offline"] is True
    assert options["market_manifest_sha256"] == "d" * 64
    assert "synthetic-secret" not in json.dumps(options["provider_config"])


def test_nlp_ablation_flags_are_explicit_not_fallback_switches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, version, _ = registered_events(tmp_path, monkeypatch)
    args = cli._parser().parse_args(
        ["build-intelligence", "--registry-version", version, "--no-finbert", "--no-gemma"]
    )
    options: dict[str, Any] = {}

    def build(*values: Any, **kwargs: Any) -> dict[str, Any]:
        options.update(kwargs)
        return {"event_count": len(values[0])}

    monkeypatch.setattr(cli, "build_event_intelligence", build)
    cli.run_command(args, paths, runtime())
    assert options["provider"] is None
    assert options["sentiment_backend"] is None


@pytest.mark.parametrize("command", ["build-intelligence", "train-models", "verify-models"])
def test_model_jobs_require_explicit_registered_version(tmp_path: Path, command: str) -> None:
    args = cli._parser().parse_args([command])
    with pytest.raises(ValueError, match="explicit"):
        cli.run_command(args, ProjectPaths(PROJECT, tmp_path), runtime())


def test_train_and_verify_dispatch_to_explicit_bound_native_model_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Any, ...]] = []
    paths = ProjectPaths(PROJECT, tmp_path)

    def train(*values: Any, **options: Any) -> dict[str, Any]:
        calls.append((*values, options))
        return {"research_version": "trained"}

    def verify(*values: Any) -> dict[str, Any]:
        calls.append(values)
        return {"research_version": "verified"}

    monkeypatch.setattr(cli, "train_research_models", train)
    monkeypatch.setattr(cli, "verify_research_models", verify)
    train_args = cli._parser().parse_args(
        ["train-models", "--registry-version", "registry", "--horizon", "30"]
    )
    verify_args = cli._parser().parse_args(["verify-models", "--model-version", "model"])
    assert cli.run_command(train_args, paths, runtime())["research_version"] == "trained"
    assert cli.run_command(verify_args, paths, runtime())["research_version"] == "verified"
    assert calls[0][3] == {"horizon": 30}
    assert calls[1] == (paths, "model")


def test_main_defaults_to_isolated_workspace_and_redacts_error_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: list[ProjectPaths] = []

    def job(args: Any, paths: ProjectPaths, settings: RuntimeSettings) -> dict[str, Any]:
        captured.append(paths)
        return {"research_version": "test", "secret_unused_field": "must-not-print"}

    monkeypatch.setattr(cli, "run_command", job)
    monkeypatch.setattr(cli, "RuntimeSettings", lambda **kwargs: runtime())
    assert cli.main(["build-registry", "--project-root", str(PROJECT)]) == 0
    assert captured[0].workspace_root == PROJECT / "data/research_v2"
    assert "must-not-print" not in capsys.readouterr().out

    def fail(*values: Any) -> Any:
        raise ValueError("synthetic-secret-never-log")

    monkeypatch.setattr(cli, "run_command", fail)
    assert (
        cli.main(
            ["build-registry", "--project-root", str(PROJECT), "--workspace-root", str(tmp_path)]
        )
        == 1
    )
    error = capsys.readouterr().err
    assert "ValueError" in error
    assert "synthetic-secret" not in error


def test_main_blocks_canonical_workspace_and_invalid_partial_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any) -> Any:
        raise AssertionError("Invalid scientific arguments must never dispatch a batch")

    monkeypatch.setattr(cli, "run_command", forbidden)
    assert cli.main(["build-registry", "--workspace-root", str(PROJECT)]) == 1
    assert cli.main(["collect-sec", "--max-issuers", "0"]) == 1
    assert cli.main(["build-intelligence", "--max-events", "-1"]) == 1


@pytest.mark.parametrize("nlp", [False, True])
def test_colab_keeps_optional_nlp_extra_in_every_uv_run(
    monkeypatch: pytest.MonkeyPatch, nlp: bool
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(colab_bootstrap.shutil, "which", lambda name: "uv")
    monkeypatch.setattr(
        colab_bootstrap.subprocess, "run", lambda command, **kwargs: commands.append(command)
    )
    arguments = [
        "colab_bootstrap.py",
        "--data-fixture",
        "--relationship-fixture",
        "--intelligence-fixture",
    ]
    if nlp:
        arguments.append("--nlp")
    monkeypatch.setattr(sys, "argv", arguments)
    colab_bootstrap.main()
    sync = next(command for command in commands if command[1] == "sync")
    runs = [command for command in commands if command[1] == "run"]
    assert len(runs) == 15
    assert ("--extra" in sync) is nlp
    assert all(("--extra" in command) is nlp for command in runs)
    if nlp:
        assert sync[sync.index("--extra") + 1] == "nlp"
        assert all(command[command.index("--extra") + 1] == "nlp" for command in runs)

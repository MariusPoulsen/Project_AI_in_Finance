"""Accepted historical experiment: frozen policies, immutable artifacts, independent replay.

The synthetic registered workspace stands in for an accepted generation. A real
accepted binding comes only from `bind_accepted`/`load_primary` (exercised by the
CLI refusal test); here the sources are constructed directly with an accepted
binding so the experiment mechanics can be tested offline.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

from structural_break.backtest import cli
from structural_break.backtest.historical import HistoricalSources, bind_unaccepted
from structural_break.backtest.historical_experiment import (
    ARTIFACT_NAMES,
    read_manifest,
    run_historical_experiment,
    verify_historical_experiment,
)
from structural_break.research.primary import PrimaryNotReadyError
from tests.historical_workspace import make_workspace

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
HEADLINE = "threshold=0.3|phase6-execution-v2-20261016"


def _sources(root: Path, *, accepted: bool = True, horizon: int = 20) -> HistoricalSources:
    relative, sha = make_workspace(root, horizon=horizon)
    binding = bind_unaccepted(root, relative, sha)
    if accepted:
        # Test-only stand-in for a published binding (production derives it via load_primary).
        binding = binding.model_copy(
            update={"acceptance": "ACCEPTED", "primary_version": "research_primary_" + "a" * 24}
        )
    return HistoricalSources(root, binding)


@pytest.fixture
def experiment(tmp_path: Path) -> tuple[HistoricalSources, Path]:
    sources = _sources(tmp_path / "workspace")
    return sources, run_historical_experiment(sources, CONFIGS, tmp_path / "out")


def _reports(manifest: Path) -> dict[str, dict[str, object]]:
    return dict(json.loads((manifest.parent / "reports.json").read_text(encoding="utf-8")))


def test_experiment_binds_frozen_policies_and_declared_combinations(
    experiment: tuple[HistoricalSources, Path],
) -> None:
    _, path = experiment
    manifest = read_manifest(path)
    assert path.parent.name == manifest.experiment_id
    assert sorted(item.name for item in path.parent.iterdir()) == sorted(
        (*ARTIFACT_NAMES, "manifest.json")
    )
    assert (manifest.post_hoc_development, manifest.full_system) == (True, "NOT_RUN")
    assert manifest.final_test_unlocked is False and manifest.economic_claims_validated is False
    assert manifest.identity.binding.acceptance == "ACCEPTED"
    assert manifest.event_count == 3 and manifest.horizon_sessions == 20
    roles = [item.role for item in manifest.combinations]
    assert roles.count("HEADLINE") == 1 and roles[0] == "HEADLINE"
    assert roles.count("THRESHOLD_SENSITIVITY") == 3
    assert roles.count("EXECUTION_SENSITIVITY") == 21
    assert manifest.combinations[0].key == HEADLINE
    policies = json.loads((path.parent / "policies.json").read_text(encoding="utf-8"))
    assert len(policies["policies"]) == 22
    assert {policy["status"] for policy in policies["policies"]} == {"FROZEN"}


def test_reports_are_post_hoc_development_with_full_system_not_run(
    experiment: tuple[HistoricalSources, Path],
) -> None:
    _, path = experiment
    reports = _reports(path)
    headline = reports[HEADLINE]
    assert headline["data_kind"] == "DEVELOPMENT_CAPTURE"
    assert headline["post_hoc_development"] is True
    rungs = headline["natural_rungs"]
    assert isinstance(rungs, dict)
    assert rungs["FULL_SYSTEM"]["status"] == "NOT_RUN"
    # E1 is ACTIVE with A 0.25 and B 0.70: at 0.30 only B selects it; at 0.20 both do.
    assert (rungs["MODEL_A"]["selected_n"], rungs["MODEL_B"]["selected_n"]) == (0, 1)
    low = reports["threshold=0.2|phase6-execution-v2-20261016"]["natural_rungs"]
    assert isinstance(low, dict)
    assert (low["MODEL_A"]["selected_n"], low["MODEL_B"]["selected_n"]) == (1, 1)
    economics = rungs["MODEL_B"]["selected_economics"]
    assert economics["status_counts"]["COMPLETE"] == 1
    assert economics["return_policy"].startswith("COMPLETE_ONLY")
    stressed = reports["threshold=0.3|phase6-execution-v2-20261016:cost=20bps,borrow=0.1"]
    stressed_b = stressed["natural_rungs"]["MODEL_B"]["selected_economics"]  # type: ignore[index]
    assert stressed_b["mean_net_return"] < economics["mean_net_return"]
    summary = (path.parent / "summary.md").read_text(encoding="utf-8")
    assert "not a final-test result" in summary and "| FULL_SYSTEM | 3 | not run |" in summary


def test_rerun_is_idempotent_and_verification_replays_every_artifact(
    experiment: tuple[HistoricalSources, Path], tmp_path: Path
) -> None:
    sources, path = experiment
    assert run_historical_experiment(sources, CONFIGS, tmp_path / "out") == path
    result = verify_historical_experiment(path, sources, CONFIGS)
    assert result["status"] == "VERIFIED_HISTORICAL_REPLAY"
    assert result["combinations"] == 25 and result["full_system"] == "NOT_RUN"


def test_rewritten_outputs_with_rehashed_manifest_fail_replay(
    experiment: tuple[HistoricalSources, Path],
) -> None:
    sources, path = experiment
    reports = path.parent / "reports.json"
    raw = reports.read_bytes().replace(
        b'"post_hoc_development":true', b'"post_hoc_development":false'
    )
    reports.write_bytes(raw)
    with pytest.raises(ValueError, match="checksum"):
        verify_historical_experiment(path, sources, CONFIGS)
    import hashlib

    manifest = json.loads(path.read_text(encoding="utf-8"))
    for item in manifest["artifacts"]:
        if item["path"] == "reports.json":
            item.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="independent deterministic replay"):
        verify_historical_experiment(path, sources, CONFIGS)


def test_unaccepted_sources_cannot_run_an_experiment(tmp_path: Path) -> None:
    sources = _sources(tmp_path / "workspace", accepted=False)
    with pytest.raises(ValueError, match="accepted generation binding"):
        run_historical_experiment(sources, CONFIGS, tmp_path / "out")


def test_verification_refuses_other_generations_or_changed_policies(
    experiment: tuple[HistoricalSources, Path], tmp_path: Path
) -> None:
    _, path = experiment
    other = _sources(tmp_path / "other", horizon=10)
    with pytest.raises(ValueError, match="do not reproduce"):
        verify_historical_experiment(path, other, CONFIGS)
    sources, _ = experiment
    configs = tmp_path / "configs"
    configs.mkdir()
    for name in ("phase6_execution.json", "phase6_execution_sensitivities.json"):
        shutil.copy(CONFIGS / name, configs / name)
    sensitivities = configs / "phase6_execution_sensitivities.json"
    value = json.loads(sensitivities.read_text(encoding="utf-8"))
    value["positive_beta_limits"] = [2.0, 100.0]
    sensitivities.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="configs differ from the bound policy set"):
        verify_historical_experiment(path, sources, configs)


def test_cli_offers_only_accepted_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "workspace"
    relative, sha = make_workspace(root, horizon=20)
    base = ["structural-break-backtest", "historical-experiment", "--workspace-root", str(root)]
    monkeypatch.setattr(
        sys,
        "argv",
        [*base, "--evaluation-manifest", relative, "--evaluation-sha256", sha, "--output-dir", "x"],
    )
    with pytest.raises(SystemExit):
        cli.main()
    monkeypatch.setattr(sys, "argv", [*base, "--output-dir", str(tmp_path / "out")])
    with pytest.raises(PrimaryNotReadyError):
        cli.main()

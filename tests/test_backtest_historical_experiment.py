"""Accepted historical experiment: frozen policies, immutable artifacts, independent replay.

The synthetic registered workspace stands in for an accepted generation. A real
accepted binding comes only from `bind_accepted`/`load_primary` (exercised by the
CLI refusal test); here the sources are constructed directly with an accepted
binding so the experiment mechanics can be tested offline.
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

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

REPOSITORY_CONFIGS = Path(__file__).resolve().parents[1] / "configs"
CONFIG_NAMES = (
    "phase6_execution.json",
    "phase6_execution_sensitivities.json",
    "phase6_analysis.json",
)
HEADLINE = "threshold=0.3|phase6-execution-v2-20261016"
Experiment = tuple[HistoricalSources, Path, Path]


def _configs(directory: Path, *, robustness: str = "FROZEN") -> Path:
    """Repository configs; the robustness status is set here only as a test stand-in."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in CONFIG_NAMES:
        shutil.copy(REPOSITORY_CONFIGS / name, directory / name)
    analysis = directory / "phase6_analysis.json"
    value = json.loads(analysis.read_text(encoding="utf-8"))
    value["robustness"]["status"] = robustness
    analysis.write_text(json.dumps(value), encoding="utf-8")
    return directory


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
def experiment(tmp_path: Path) -> Experiment:
    sources = _sources(tmp_path / "workspace")
    configs = _configs(tmp_path / "configs")
    return sources, run_historical_experiment(sources, configs, tmp_path / "out"), configs


def _artifact(manifest: Path, name: str) -> Any:
    return json.loads((manifest.parent / name).read_text(encoding="utf-8"))


def test_experiment_binds_frozen_policies_and_declared_combinations(
    experiment: Experiment,
) -> None:
    _, path, _ = experiment
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
    policies = _artifact(path, "policies.json")
    assert len(policies["policies"]) == 22
    assert {policy["status"] for policy in policies["policies"]} == {"FROZEN"}


def test_repository_robustness_policy_awaits_owner_approval(tmp_path: Path) -> None:
    sources = _sources(tmp_path / "workspace")
    with pytest.raises(ValueError, match="awaits owner approval"):
        run_historical_experiment(sources, REPOSITORY_CONFIGS, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_reports_are_post_hoc_development_with_full_system_not_run(
    experiment: Experiment,
) -> None:
    _, path, _ = experiment
    reports = _artifact(path, "reports.json")
    headline = reports[HEADLINE]
    assert headline["data_kind"] == "DEVELOPMENT_CAPTURE"
    assert headline["post_hoc_development"] is True
    rungs = headline["natural_rungs"]
    assert rungs["FULL_SYSTEM"]["status"] == "NOT_RUN"
    # E1 is ACTIVE with A 0.25 and B 0.70: at 0.30 only B selects it; at 0.20 both do.
    assert (rungs["MODEL_A"]["selected_n"], rungs["MODEL_B"]["selected_n"]) == (0, 1)
    low = reports["threshold=0.2|phase6-execution-v2-20261016"]["natural_rungs"]
    assert (low["MODEL_A"]["selected_n"], low["MODEL_B"]["selected_n"]) == (1, 1)
    economics = rungs["MODEL_B"]["selected_economics"]
    assert economics["status_counts"]["COMPLETE"] == 1
    assert economics["return_policy"].startswith("COMPLETE_ONLY")
    stressed = reports["threshold=0.3|phase6-execution-v2-20261016:cost=20bps,borrow=0.1"]
    stressed_b = stressed["natural_rungs"]["MODEL_B"]["selected_economics"]
    assert stressed_b["mean_net_return"] < economics["mean_net_return"]
    summary = (path.parent / "summary.md").read_text(encoding="utf-8")
    assert "not a final-test result" in summary and "| FULL_SYSTEM | 3 | not run |" in summary


def test_cost_grid_bootstrap_and_robustness_use_frozen_policies(experiment: Experiment) -> None:
    _, path, _ = experiment
    grid = _artifact(path, "cost-grid.json")
    assert grid["scenario_n"] == 16 and grid["winner_selected"] is False
    assert {(row["cost_bps_per_side"], row["annual_borrow_rate"]) for row in grid["scenarios"]} == {
        (cost, borrow) for cost in (2.5, 5.0, 10.0, 20.0) for borrow in (0.0, 0.01, 0.03, 0.1)
    }
    assert all(row["rungs"]["FULL_SYSTEM"] == {"status": "NOT_RUN"} for row in grid["scenarios"])
    uncertainty = _artifact(path, "uncertainty.json")
    assert uncertainty["data_kind"] == "DEVELOPMENT_CAPTURE"
    assert uncertainty["policy"]["status"] == "FROZEN"
    assert (uncertainty["policy"]["replicates"], uncertainty["policy"]["seed"]) == (2000, 5557)
    assert uncertainty["comparisons"]["MODEL_B__FULL_SYSTEM"]["status"] == "NOT_RUN"
    assert uncertainty["populated_calendar_month_blocks_n"] == 2
    natural = uncertainty["comparisons"]["BASELINE_0__BASELINE_1"]["natural_selected_complete"]
    assert natural["bootstrap"]["interval_unavailable_reason"] == (
        "INSUFFICIENT_POPULATED_CALENDAR_MONTHS"
    )
    contexts = _artifact(path, "contexts.json")["contexts"]
    assert {context["event_id"] for context in contexts} == {"E1", "E3"}
    robustness = _artifact(path, "robustness.json")
    assert robustness["data_kind"] == "DEVELOPMENT_CAPTURE"
    assert robustness["context_missing_n"] == 1
    assert set(robustness["slices"]["vix_stress"]) == {"LOW", "HIGH", "UNKNOWN"}
    assert set(robustness["slices"]["volatility_stress"]) == {"LOW", "HIGH", "UNKNOWN"}
    assert set(robustness["slices"]["event_type"]) == {"UNKNOWN"}


def test_portfolios_run_per_rung_with_unknown_nav_kept_explicit(experiment: Experiment) -> None:
    _, path, _ = experiment
    portfolios = _artifact(path, "portfolios.json")
    assert portfolios["FULL_SYSTEM"]["status"] == "NOT_RUN"
    model_b = portfolios["MODEL_B"]
    assert model_b["mode"] == "DEVELOPMENT_CAPTURE"
    assert "POST_HOC_DEVELOPMENT_ASSESSMENT_NOT_FINAL_TEST" in model_b["limitations"]
    statuses = {trade["event_id"]: trade["status"] for trade in model_b["trades"]}
    assert statuses == {"E1": "COMPLETE", "E3": "NOT_SELECTED", "E2": "NOT_SELECTED"}
    assert model_b["final_nav"] is not None and model_b["unknown_nav_since"] is None
    baseline = portfolios["BASELINE_0"]
    statuses = {trade["event_id"]: trade["status"] for trade in baseline["trades"]}
    assert statuses == {"E1": "COMPLETE", "E3": "NOT_ENTERED", "E2": "UNPRICED"}
    # The E2 path is truncated before 2024, so later NAV is unknown rather than repaired.
    assert baseline["final_nav"] is None and baseline["unknown_nav_since"] is not None
    summary = (path.parent / "summary.md").read_text(encoding="utf-8")
    assert "| FULL_SYSTEM | not run | - | - | - |" in summary


def test_rerun_is_idempotent_and_verification_replays_every_artifact(
    experiment: Experiment, tmp_path: Path
) -> None:
    sources, path, configs = experiment
    assert run_historical_experiment(sources, configs, tmp_path / "out") == path
    result = verify_historical_experiment(path, sources, configs)
    assert result["status"] == "VERIFIED_HISTORICAL_REPLAY"
    assert result["combinations"] == 25 and result["full_system"] == "NOT_RUN"


@pytest.mark.parametrize("name", ["reports.json", "portfolios.json", "robustness.json"])
def test_rewritten_outputs_with_rehashed_manifest_fail_replay(
    experiment: Experiment, name: str
) -> None:
    sources, path, configs = experiment
    artifact = path.parent / name
    raw = artifact.read_bytes().replace(b'"DEVELOPMENT_CAPTURE"', b'"SYNTHETIC_FIXTURE"', 1)
    assert raw != artifact.read_bytes()
    artifact.write_bytes(raw)
    with pytest.raises(ValueError, match="checksum"):
        verify_historical_experiment(path, sources, configs)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for item in manifest["artifacts"]:
        if item["path"] == name:
            item.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="independent deterministic replay"):
        verify_historical_experiment(path, sources, configs)


def test_unaccepted_sources_cannot_run_an_experiment(tmp_path: Path) -> None:
    sources = _sources(tmp_path / "workspace", accepted=False)
    with pytest.raises(ValueError, match="accepted generation binding"):
        run_historical_experiment(sources, _configs(tmp_path / "configs"), tmp_path / "out")


def test_verification_refuses_other_generations_or_changed_policies(
    experiment: Experiment, tmp_path: Path
) -> None:
    sources, path, configs = experiment
    other = _sources(tmp_path / "other", horizon=10)
    with pytest.raises(ValueError, match="do not reproduce"):
        verify_historical_experiment(path, other, configs)
    changed = _configs(tmp_path / "changed")
    sensitivities = changed / "phase6_execution_sensitivities.json"
    value = json.loads(sensitivities.read_text(encoding="utf-8"))
    value["positive_beta_limits"] = [2.0, 100.0]
    sensitivities.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="configs differ from the bound policy set"):
        verify_historical_experiment(path, sources, changed)
    analysis_changed = _configs(tmp_path / "analysis")
    analysis = analysis_changed / "phase6_analysis.json"
    value = json.loads(analysis.read_text(encoding="utf-8"))
    value["robustness"]["vix_high"] = 35.0
    analysis.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="configs differ from the bound policy set"):
        verify_historical_experiment(path, sources, analysis_changed)


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

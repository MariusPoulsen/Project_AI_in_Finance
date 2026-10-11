"""Persist/replay every analysis artifact without accepting synthetic research."""

import json
import sys
from pathlib import Path

import pytest

from structural_break.backtest import analysis, cli
from structural_break.backtest.costs import CostGridPolicy
from structural_break.backtest.experiment import checksum
from structural_break.backtest.uncertainty import EconomicBootstrapPolicy


def publish(path: Path) -> Path:
    declared = analysis.fixture_analysis_inputs()
    declared["bootstrap-policy.json"] = EconomicBootstrapPolicy(replicates=100)
    declared["cost-grid.json"] = CostGridPolicy(turnover_bps=(5.0,), annual_borrow_rates=(0.03,))
    return analysis.run_analysis(declared, path)


def test_complete_bundle_replays_idempotently_and_retains_all_policies(tmp_path: Path) -> None:
    manifest = publish(tmp_path)
    before = {path.name: path.read_bytes() for path in manifest.parent.iterdir()}
    assert publish(tmp_path) == manifest
    verified = analysis.verify_analysis(manifest)
    assert verified["status"] == "VERIFIED_SYNTHETIC_ANALYSIS"
    assert verified["ladder_events_n"] == 14
    assert verified["portfolio_proposals_n"] == 2
    assert verified["scientific_acceptance"] is verified["final_test_unlocked"] is False
    assert before == {path.name: path.read_bytes() for path in manifest.parent.iterdir()}
    portfolio = json.loads((manifest.parent / "portfolio-result.json").read_bytes())
    assert portfolio["final_nav"] == pytest.approx(1.0494718253968256)
    assert set(before) == {"manifest.json", *analysis.ARTIFACT_NAMES}


@pytest.mark.parametrize("name", analysis.OUTPUT_NAMES)
def test_rehashed_forged_output_cannot_pass_fresh_analysis_replay(
    tmp_path: Path, name: str
) -> None:
    manifest = publish(tmp_path)
    data = b"untrue" if name.endswith(".md") else b'{"fabricated":true}'
    (manifest.parent / name).write_bytes(data)
    payload = json.loads(manifest.read_bytes())
    for binding in payload["artifacts"]:
        if binding["path"] == name:
            binding.update(sha256=checksum(data), size_bytes=len(data))
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="independent deterministic replay"):
        analysis.verify_analysis(manifest)


def test_changed_input_does_not_pass_by_rehashing_artifact_only(tmp_path: Path) -> None:
    manifest = publish(tmp_path)
    input_file = manifest.parent / "bootstrap-policy.json"
    payload = json.loads(input_file.read_bytes())
    payload["seed"] += 1
    data = json.dumps(payload).encode()
    input_file.write_bytes(data)
    payload = json.loads(manifest.read_bytes())
    for binding in payload["artifacts"]:
        if binding["path"] == input_file.name:
            binding.update(sha256=checksum(data), size_bytes=len(data))
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="inputs, source or runtime"):
        analysis.verify_analysis(manifest)


def test_source_drift_prevents_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    records = analysis._sources()
    calls = 0

    def changed() -> tuple[analysis.SourceBinding, ...]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return records
        return (records[0].model_copy(update={"sha256": "0" * 64}), *records[1:])

    monkeypatch.setattr(analysis, "_sources", changed)
    with pytest.raises(ValueError, match="changed during computation"):
        publish(tmp_path)
    assert not list(tmp_path.rglob("manifest.json"))


def test_analysis_cli_uses_full_grid_and_separate_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["backtest", "analysis", "--fixture", "--output-dir", str(tmp_path)]
    )
    cli.main()
    receipt = json.loads(capsys.readouterr().out)
    manifest = Path(receipt["manifest"])
    cost_report = json.loads((manifest.parent / "cost-report.json").read_bytes())
    assert cost_report["scenario_n"] == 12
    monkeypatch.setattr(sys, "argv", ["backtest", "verify-analysis", "--manifest", str(manifest)])
    cli.main()
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED_SYNTHETIC_ANALYSIS"

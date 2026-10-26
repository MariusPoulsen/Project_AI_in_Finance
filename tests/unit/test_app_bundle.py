"""App bundles: verified, read-only presentation tables (WS2 / PLAN P7).

The synthetic bundle is invented data run through the project's real matched
evaluation; the workspace test reuses the registered publication fixture.
"""

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_primary_research import release as release
from test_team_snapshot import accepted_team as accepted_team

from structural_break.app_bundle.analytics import events_table, model_curves
from structural_break.app_bundle.cli import main as bundle_cli
from structural_break.app_bundle.io import BundleError, read_bundle, write_bundle
from structural_break.app_bundle.strategy import ExperimentMismatchError, compact_experiment
from structural_break.app_bundle.synthetic import synthetic_bundle
from structural_break.app_bundle.workspace import build_from_workspace, choose_showcase
from structural_break.services.research_application import (
    ResearchApplicationService,
    ScannerFilters,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
assert release is not None and accepted_team is not None  # imported fixtures


@pytest.fixture(scope="module")
def bundle():
    return synthetic_bundle(pairs=6, small=True, seed=11)


@pytest.fixture(scope="module")
def service(bundle):
    return ResearchApplicationService(bundle)


def test_synthetic_bundle_is_marked_and_uses_the_real_report_structure(bundle):
    identity = bundle.identity
    assert identity.synthetic and identity.source == "synthetic"
    assert identity.primary_version.startswith("SYNTHETIC_PREVIEW")
    assert set(bundle.horizons) == {20, 10, 30}
    report = bundle.horizons[20].report
    assert report["final_test_read"] is False
    assert set(report["models"]) == {"logistic", "xgboost"}
    paired = report["models"]["logistic"]["B_both"]["paired_assessment"]
    assert len(paired["quarter_block_percentile_interval_95"]) == 2
    events = bundle.horizons[20].events
    end = pd.Timestamp(identity.protocol["development_end"]).date()
    assert pd.to_datetime(events["event_date"]).dt.date.le(end).all()


def test_explanations_add_back_up_to_each_saved_model_margin(bundle):
    data = bundle.horizons[20]
    totals = data.contribution_totals
    parts = data.contributions.groupby(["event_id", "model"])["contribution"].sum()
    merged = totals.set_index(["event_id", "model"]).join(parts.rename("top"))
    reconstructed = merged["base"] + merged["top"] + merged["other"]
    assert np.allclose(reconstructed, merged["margin"], atol=1e-5)
    assert set(totals["model"]) == {"logistic_A", "logistic_B_both", "xgboost_A", "xgboost_B_both"}
    events = data.events.set_index("event_id")
    logistic = totals.loc[totals["model"].eq("logistic_B_both")].set_index("event_id")
    stored = events.loc[logistic.index, "logistic_B_both_calibrated"].astype(float)
    assert np.allclose(logistic["calibrated_probability"], stored, atol=1e-6)


def test_curves_summarise_assessment_rows_only(bundle):
    data = bundle.horizons[20]
    curves = data.curves
    roc = curves.loc[curves["kind"].eq("roc") & curves["variant"].eq("A")]
    assert roc["x"].iloc[-1] == pytest.approx(1.0) and roc["y"].iloc[-1] == pytest.approx(1.0)
    reliability = curves.loc[
        curves["kind"].eq("reliability")
        & curves["family"].eq("logistic")
        & curves["variant"].eq("A")
    ]
    assessed = data.events["research_partition"].eq("assessment").sum()
    assert reliability["n"].sum() == assessed


def test_events_table_keeps_unknown_catalysts_unknown():
    predictions = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "event_date": ["2022-01-03", "2022-01-04"],
            "pair_id": ["A__B", "A__B"],
            "research_partition": ["assessment"] * 2,
            "y_revert_success": [1, 0],
            "logistic_A_calibrated": [0.2, 0.3],
        }
    )
    inputs = pd.DataFrame(
        {
            "event_id": ["e1", "e2"],
            "event_type_EARNINGS": [1.0, 0.0],
            "event_type_UNKNOWN": [0.0, 0.0],
            "evidence_available": [1.0, 0.0],
        }
    )
    rows = events_table(predictions, inputs)
    assert rows["catalyst_event_type"].tolist() == ["EARNINGS", "UNKNOWN"]
    assert rows.columns.is_unique
    assert model_curves(predictions.assign(research_partition="fit")).empty


def test_bundle_round_trip_verifies_every_checksum(bundle, tmp_path):
    manifest = write_bundle(bundle, tmp_path / "bundle")
    loaded = read_bundle(manifest.parent)
    assert loaded.identity.bundle_id == bundle.identity.bundle_id
    assert loaded.identity.synthetic
    assert len(loaded.horizons[20].events) == len(bundle.horizons[20].events)
    assert loaded.horizons[20].strategy["final_test_read"] is False
    with pytest.raises(FileExistsError):
        write_bundle(bundle, tmp_path / "bundle")
    tampered = tmp_path / "tampered"
    shutil.copytree(manifest.parent, tampered)
    events = pd.read_parquet(tampered / "h20/events.parquet")
    events.loc[0, "logistic_B_both_calibrated"] = 0.99
    events.to_parquet(tampered / "h20/events.parquet", index=False)
    with pytest.raises(BundleError, match="checksum"):
        read_bundle(tampered)
    unlocked = tmp_path / "unlocked"
    shutil.copytree(manifest.parent, unlocked)
    document = json.loads((unlocked / "bundle.json").read_text())
    document["final_test_read"] = True
    (unlocked / "bundle.json").write_text(json.dumps(document))
    with pytest.raises(BundleError, match="final test"):
        read_bundle(unlocked)
    with pytest.raises(BundleError):
        read_bundle(tmp_path / "missing")


def test_service_queries_keep_denominators_and_honest_verdicts(service):
    headline = service.headline(20)
    tone, sentence = service.verdict(headline)
    low, high = headline.interval
    if low <= 0 <= high:
        assert tone == "inconclusive" and "includes zero" in sentence
    comparison = service.comparison(20)
    assert len(comparison) == 10 and comparison["primary"].sum() == 2
    assert comparison.loc[comparison["variant"].eq("A"), "delta_brier_B_minus_A"].isna().all()
    protocol = service.protocol
    rows = service.scanner(
        20,
        ScannerFilters(
            start=pd.Timestamp(protocol["assessment_start"]).date(),
            end=pd.Timestamp(protocol["assessment_end"]).date(),
        ),
    )
    assert len(rows) == service.data(20).events["research_partition"].eq("assessment").sum()
    assert rows["p_B"].between(0, 1).all()
    pair = service.hero_pair(20)
    assert pair is not None and service.pair_series(pair) is not None
    event = rows.iloc[0]["event_id"]
    assert service.explanation(20, event, "logistic_B_both") is not None
    evidence = service.evidence(20, event)
    if evidence["Catalyst type"] == "UNKNOWN":
        assert evidence["Extraction confidence"] == "UNKNOWN"
    assert {"fit", "calibration", "assessment"} <= set(service.cohorts(20)["period"])
    assert not service.coverage_table(20).empty
    assert len(service.inventory(20)) == 10
    assert set(service.strategy_rungs(20)["rung"]) >= {"MODEL_A", "MODEL_B", "FULL_SYSTEM"}


def test_synthetic_cli_writes_then_verifies(tmp_path, capsys):
    output = tmp_path / "preview"
    assert bundle_cli(["synthetic", "--output", str(output), "--pairs", "4", "--small"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["synthetic"] is True and summary["final_test_read"] is False
    assert bundle_cli(["verify", "--bundle", str(output)]) == 0


def test_workspace_bundle_reads_only_the_accepted_publication(accepted_team, tmp_path):
    paths, primary = accepted_team
    before = sorted(p.relative_to(paths.workspace_root) for p in paths.workspace_root.rglob("*"))
    bundle = build_from_workspace(paths)
    after = sorted(p.relative_to(paths.workspace_root) for p in paths.workspace_root.rglob("*"))
    assert before == after  # nothing written into the workspace
    assert bundle.identity.primary_version == primary["primary_version"]
    assert not bundle.identity.synthetic
    assert bundle.identity.explanation_status == "AVAILABLE"
    data = bundle.horizons[20]
    assert len(data.events) == 4 and data.contribution_totals["event_id"].nunique() == 4
    assert bundle.pair_loader is not None
    written = write_bundle(bundle, tmp_path / "exported")
    assert read_bundle(written.parent).identity.bundle_id == bundle.identity.bundle_id
    with pytest.raises(ValueError, match="Unknown pair"):
        choose_showcase(data.events, 2, ["NOT__APAIR"])


def test_experiments_from_another_generation_are_refused(tmp_path):
    import test_backtest_historical_experiment as fixture

    from structural_break.backtest.historical_experiment import run_historical_experiment

    sources = fixture._sources(tmp_path / "workspace")
    manifest = run_historical_experiment(
        sources, fixture._configs(tmp_path / "configs"), tmp_path / "out"
    )
    evaluation = sources.binding.evaluation.version
    horizon, summary, nav, trades = compact_experiment(
        manifest, primary_version="research_primary_" + "a" * 24, evaluation_version=evaluation
    )
    assert horizon == 20 and summary["final_test_read"] is False
    assert summary["full_system"] == "NOT_RUN"
    assert {"BASELINE_0", "MODEL_B"} <= set(trades.columns)
    assert not nav.empty
    with pytest.raises(ExperimentMismatchError):
        compact_experiment(manifest, primary_version="other", evaluation_version=evaluation)
    artifact = manifest.parent / "reports.json"
    artifact.write_text(artifact.read_text().replace("BASELINE_0", "BASELINE_X", 1))
    with pytest.raises(ValueError, match="checksum"):
        compact_experiment(
            manifest, primary_version="research_primary_" + "a" * 24, evaluation_version=evaluation
        )

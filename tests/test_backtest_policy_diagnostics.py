"""Target-blind execution-policy diagnostics on the synthetic registered workspace."""

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from structural_break.backtest import cli
from structural_break.backtest.contracts import canonical_sessions
from structural_break.backtest.historical import HistoricalSources, bind_unaccepted
from structural_break.backtest.policy_diagnostics import (
    beta_summary,
    liquidity_summary,
    policy_diagnostics,
    score_summary,
)
from tests.historical_workspace import make_workspace

# E1 (2023-11-06), S1 (2023-11-20) and E3 (2023-11-10) fall before this assessment
# start; E2 (2023-12-20) is assessment-only and must never be read.
PRE_ASSESSMENT = {
    "fit_start": "2023-10-02",
    "calibration_start": "2023-11-01",
    "calibration_end": "2023-11-30",
    "assessment_start": "2023-12-01",
}


def _sources(tmp_path: Path, **protocol: str) -> HistoricalSources:
    root = tmp_path / "workspace"
    relative, sha = make_workspace(root, protocol_overrides={**PRE_ASSESSMENT, **protocol})
    return HistoricalSources.open(root, bind_unaccepted(root, relative, sha))


def test_diagnostics_read_only_pre_assessment_rows_and_no_labels(tmp_path: Path) -> None:
    report = policy_diagnostics(_sources(tmp_path))
    assert report["window"] == {"start": "2023-10-02", "end": "2023-11-30"}
    assert (report["labels_read"], report["assessment_data_read"]) == (False, False)
    assert report["returns_computed"] is False
    assert report["raw_crossing_beta"]["all"]["n"] == 3
    assert report["raw_crossing_beta"]["active"]["n"] == 2
    assert report["episode_event_beta"]["n"] == 2
    assert report["episode_event_beta"]["positive_beta_above_ceiling_n"] == {
        "2.0": 0,
        "3.0": 0,
        "5.0": 0,
    }
    liquidity = report["episode_event_liquidity"]
    assert liquidity["n"] == 2 and liquidity["unknown_n"] == 0
    assert liquidity["price_floor"] == "NOT_COMPUTED_RETROSPECTIVE_SPLIT_ADJUSTMENT"
    scores = report["calibration_scores"]["logistic_A"]
    assert scores["all"]["n"] == 2
    assert scores["baseline1_eligible"]["n"] == 1
    assert scores["all"]["at_or_above_n"]["0.65"] == 0


def test_prediction_reads_refuse_supervised_target_columns(tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    with pytest.raises(ValueError, match="supervised target"):
        sources.predictions(["event_id", "y_revert_success"])


def test_calibration_must_precede_the_assessment_window(tmp_path: Path) -> None:
    sources = _sources(tmp_path, calibration_end="2023-12-05")
    with pytest.raises(ValueError, match="before the assessment"):
        policy_diagnostics(sources)


def test_pure_summaries_count_ceilings_floors_and_thresholds() -> None:
    betas = beta_summary(pd.DataFrame({"beta": [-0.5, 0.5, 2.5, 4.0, 6.0, None]}))
    assert betas["nonpositive_beta_n"] == 1 and betas["missing_beta_n"] == 1
    assert betas["positive_beta_above_ceiling_n"] == {"2.0": 3, "3.0": 2, "5.0": 1}
    days = [row[0] for row in canonical_sessions(date(2023, 1, 3), date(2023, 2, 15))][:21]
    prices = pd.DataFrame(
        [
            {"ticker": ticker, "trading_date": day, "dollar_volume": volume}
            for ticker, volume in (("AAA", 2e6), ("BBB", 3e7))
            for day in days
        ]
    )
    universe = pd.DataFrame([{"pair_id": "AAA__BBB", "leg_a": "AAA", "leg_b": "BBB"}])
    events = pd.DataFrame(
        [
            {"pair_id": "AAA__BBB", "event_date": days[-1]},
            {"pair_id": "AAA__BBB", "event_date": days[5]},
        ]
    )
    liquidity = liquidity_summary(events, universe, prices)
    assert liquidity["unknown_n"] == 1
    assert liquidity["below_floor_n"] == {
        "1000000": 0,
        "5000000": 1,
        "10000000": 1,
        "25000000": 1,
    }
    scores = score_summary(
        pd.DataFrame({"m_calibrated": [0.1, 0.35, 0.7], "baseline1_eligible": [True, False, True]}),
        ["m"],
    )
    assert scores["m"]["all"]["at_or_above_n"]["0.3"] == 2
    assert scores["m"]["baseline1_eligible"]["at_or_above_n"]["0.65"] == 1


def test_diagnostics_cli_is_content_addressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "workspace"
    relative, sha = make_workspace(root, protocol_overrides=PRE_ASSESSMENT)
    arguments = [
        "structural-break-backtest",
        "policy-diagnostics",
        "--workspace-root",
        str(root),
        "--evaluation-manifest",
        relative,
        "--evaluation-sha256",
        sha,
        "--horizon",
        "10",
        "--output-dir",
        str(tmp_path / "out"),
    ]
    outputs = []
    for _ in range(2):
        monkeypatch.setattr(sys, "argv", arguments)
        cli.main()
        outputs.append(json.loads(capsys.readouterr().out))
    assert outputs[0] == outputs[1]
    assert Path(outputs[0]["directory"], "diagnostics.json").is_file()

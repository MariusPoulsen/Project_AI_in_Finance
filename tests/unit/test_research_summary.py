"""Presentation integrity, locked periods and correctly aligned research comparisons."""

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from structural_break.app_ui import data
from structural_break.services.research_summary import ADOPTED, PERIODS, read_summary

SOURCE = Path(__file__).resolve().parents[2] / "demo/book"


@pytest.fixture
def snapshot(tmp_path):
    for name in (
        "presentation.json",
        *json.loads((SOURCE / "presentation.json").read_text())["files"],
    ):
        shutil.copyfile(SOURCE / name, tmp_path / name)
    return tmp_path


def reseal(folder, name):
    manifest_path = folder / "presentation.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_current_comparison_retains_matched_cohort_and_posthoc_role(snapshot):
    svc = read_summary(snapshot)
    rows = svc.forecasts(next(iter(PERIODS)))
    assert rows["ROC AUC"].tolist() == [0.711, 0.718, 0.735, 0.739]
    assert rows["id"].tolist() == ["A", "R0", "B_rule_ou", "B_rule_ou_track"]
    assert "Post-hoc" in rows.iloc[-1]["Role"]
    assert svc.manifest.cohorts[next(iter(PERIODS))].n == 10940


def test_rebase_uses_previous_close_and_drawdown_keeps_initial_capital(snapshot):
    svc = read_summary(snapshot)
    confirmation = next(iter(PERIODS))
    curves = svc.curves(confirmation)
    before = svc.daily.loc[svc.daily.session_date.dt.year.eq(2017)].iloc[-1]
    first = svc.daily.loc[svc.daily.session_date.dt.year.eq(2018)].iloc[0]
    assert curves.iloc[0][ADOPTED] == pytest.approx(first[ADOPTED] / before[ADOPTED])
    assert curves.session_date.dt.year.min() == 2018
    assert curves.session_date.dt.year.max() == 2023
    drawdown = svc.curves(confirmation, drawdown=True)
    assert (drawdown[ADOPTED] <= 0).all()
    assert np.allclose(
        drawdown[ADOPTED], curves[ADOPTED] / curves[ADOPTED].cummax().clip(lower=1) - 1
    )


def test_changed_data_cannot_reuse_verified_cache(snapshot, monkeypatch):
    monkeypatch.setenv("SB_RESEARCH_SUMMARY", str(snapshot))
    assert data.load_summary().status == "ready"
    file = snapshot / "summary.json"
    file.write_bytes(file.read_bytes() + b" ")
    outcome = data.load_summary()
    assert outcome.status == "failed" and outcome.service is None


def test_final_test_rows_rejected_even_with_matching_file_hash(snapshot):
    file = snapshot / "book_daily.parquet"
    daily = pd.read_parquet(file)
    daily.loc[len(daily)] = [pd.Timestamp("2024-01-02"), 1.7, 1.6]
    daily.to_parquet(file)
    reseal(snapshot, file.name)
    with pytest.raises(ValueError, match="final test is locked"):
        read_summary(snapshot)


def test_model_rows_cannot_be_relabelled_as_a_different_current_model(snapshot):
    file = snapshot / "summary.json"
    summary = json.loads(file.read_text())
    summary["goal1"][2]["model"] = "Full model"
    file.write_text(json.dumps(summary))
    reseal(snapshot, file.name)
    with pytest.raises(ValueError, match="role/source mismatch"):
        read_summary(snapshot)


def test_nonfinite_or_missing_forecast_does_not_become_zero(snapshot):
    file = snapshot / "summary.json"
    summary = json.loads(file.read_text())
    summary["goal1"][0]["AUC 2018-23"] = None
    file.write_text(json.dumps(summary))
    reseal(snapshot, file.name)
    with pytest.raises(ValueError):
        read_summary(snapshot)


def test_catalogue_preserves_baseline_and_full_scope_without_inventing_scores(snapshot):
    svc = read_summary(snapshot)
    rows = svc.forecast_comparison(next(iter(PERIODS))).set_index("id")
    assert rows.loc[["BASELINE_0", "BASELINE_1", "FULL"], "ROC AUC"].isna().all()
    assert "not applicable" in rows.loc["BASELINE_0", "Status"]
    assert "region" in rows.loc["FULL", "Scope"]
    assert {r["Model"] for r in svc.study.regional} == {"Desk base · no agent scores", "Full model"}


def test_corrected_books_include_best_forecaster_and_full_without_synthetic_cash_growth(snapshot):
    svc = read_summary(snapshot)
    rows = svc.book_comparison(next(iter(PERIODS)))
    assert len(rows) == 4
    assert rows.iloc[2]["sharpe"] == pytest.approx(0.4060362502)
    assert rows.iloc[3]["sharpe"] == pytest.approx(0.2502234135)
    assert rows.iloc[2:]["cagr_with_cash"].isna().all()
    assert set(svc.daily.columns) == {"session_date", *svc.summary.stats}

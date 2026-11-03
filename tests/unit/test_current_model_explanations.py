"""An offline export explains every event with the actual seed models and checks the ensemble."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from structural_break.forecast import harness
from structural_break.services.forecast_explanations import OTHER, validate

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "forecast_shap_export", ROOT / "scripts/export_forecast_shap.py"
)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def shap_app(forecasts, events, values, summary):
    import pandas as pd

    from structural_break.app_ui.results import Results
    from structural_break.app_ui.shap_view import render

    current = forecasts.copy()
    current["pair_id"] = "SYNTHETIC_A__SYNTHETIC_B"
    current["event_date"] = pd.Timestamp("2018-01-02")
    current["traded"] = False
    for key in ("r0", "bag5", "track"):
        current[f"p_{key}"] = current[f"raw_{key}"]
    tables = {"forecasts": current, "shap_events": events, "shap_values": values}
    result = Results({}, {}, {**tables, "shap_summary": summary})
    render(result, (2018, 2023))


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
@pytest.mark.usefixtures("preserve_main_module")
def test_offline_export_explains_every_event_and_reproduces_scores(tmp_path, monkeypatch):
    rng = np.random.default_rng(8)
    frame = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(64)],
            "event_date": [pd.Timestamp("2015-01-02")] * 48 + [pd.Timestamp("2018-01-02")] * 16,
            "horizon_end_date": [pd.Timestamp("2015-02-02")] * 48
            + [pd.Timestamp("2018-02-02")] * 16,
            "supervised_eligible": True,
            harness.TARGET: np.tile([0, 1], 32),
            "x1": rng.normal(size=64),
            "x2": rng.normal(size=64),
        }
    )
    columns = ("x1", "x2")
    params = {"n_estimators": 8, "max_depth": 2, "min_child_weight": 1}
    monkeypatch.setitem(harness.PARAMS, "base", params)
    monkeypatch.setitem(harness.PARAMS, "bag5", {**params, "seeds": 5, "subsample": 0.8})
    monkeypatch.setattr(harness, "load", lambda args: (frame, {}, pd.DataFrame()))
    monkeypatch.setattr(
        harness,
        "feature_sets",
        lambda base, available: {name: columns for name in ("B", "B+rule+ou", "B+rule+ou+track")},
    )
    train, _, test = harness.split(frame, 2018, "d45")
    forecasts = pd.DataFrame({"event_id": test.event_id, "year": 2018})
    for key, (_, _, params_key) in export.SPECS.items():
        model = harness._estimator(harness.PARAMS[params_key])
        model.fit(train[list(columns)], train[harness.TARGET])
        forecasts[f"raw_{key}"] = model.predict_proba(test[list(columns)])[:, 1]
    folder = tmp_path / "results"
    folder.mkdir()
    (tmp_path / "outputs/book").mkdir(parents=True)
    frame.to_parquet(tmp_path / "outputs/book/features.parquet", index=False)
    source = folder / "forecasts.parquet"
    forecasts.to_parquet(source, index=False)
    manifest = {"files": {"forecasts.parquet": export.sha(source)}}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export",
            "--results",
            str(folder),
            "--outputs-root",
            str(tmp_path / "outputs"),
            "--years",
            "2018",
            "--top",
            "1",
        ],
    )
    export.main()
    events = pd.read_parquet(folder / "shap_events.parquet")
    values = pd.read_parquet(folder / "shap_values.parquet")
    summary = pd.read_parquet(folder / "shap_summary.parquet")
    validate(events, values, forecasts, summary)
    assert set(events.seed) == {42, 43, 44, 45, 46}
    # Every event of the year is explained, with its largest input and the remainder.
    assert events.groupby("model").event_id.nunique().to_dict() == {
        "r0": len(test),
        "bag5": len(test),
        "track": len(test),
    }
    assert values.groupby(["model", "event_id"]).size().eq(2).all()
    assert values.feature.eq(OTHER).sum() == 3 * len(test)
    assert set(summary.feature) == set(columns) and summary.n.eq(len(test)).all()
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_function(
        shap_app, args=(forecasts, events, values, summary), default_timeout=45
    ).run()
    assert not app.exception and not app.error
    assert app.selectbox[0].value == "bag5"
    assert (folder / "shap.json").is_file()
    bad = events.copy()
    bad.loc[0, "margin"] += 0.1
    with pytest.raises(ValueError, match="additivity"):
        validate(bad, values, forecasts, summary)
    bad = forecasts.copy()
    bad.loc[bad.event_id.eq(events.iloc[0].event_id), "raw_r0"] += 0.1
    with pytest.raises(ValueError, match="published forecast"):
        validate(events, values, bad, summary)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["files"]["forecasts.parquet"]

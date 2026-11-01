"""An offline export explains actual seed models and verifies their published ensemble."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from structural_break.forecast import harness
from structural_break.services.forecast_explanations import validate

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "forecast_shap_export", ROOT / "scripts/export_forecast_shap.py"
)
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def shap_app(forecasts, events, values):
    import pandas as pd

    from structural_break.app_ui.results import Results
    from structural_break.app_ui.shap_view import render

    current = forecasts.copy()
    current["pair_id"] = "SYNTHETIC_A__SYNTHETIC_B"
    current["event_date"] = pd.Timestamp("2018-01-02")
    for key in ("r0", "bag5", "track"):
        current[f"p_{key}"] = current[f"raw_{key}"]
    result = Results({}, {}, {"forecasts": current, "shap_events": events, "shap_values": values})
    render(result, (2018, 2023))


def test_hash_sample_is_independent_of_outcomes():
    frame = pd.DataFrame({"event_id": list("abcdef"), "y": [0, 1, 0, 1, 0, 1]})
    assert (
        export.sample(frame, 3).event_id.tolist()
        == export.sample(frame.assign(y=1 - frame.y), 3).event_id.tolist()
    )


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
@pytest.mark.usefixtures("preserve_main_module")
def test_offline_export_reproduces_scores_and_native_seed_contributions(tmp_path, monkeypatch):
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
            "--events-per-year",
            "3",
        ],
    )
    export.main()
    events = pd.read_parquet(folder / "shap_events.parquet")
    values = pd.read_parquet(folder / "shap_values.parquet")
    validate(events, values, forecasts)
    assert set(events.seed) == {42, 43, 44, 45, 46}
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_function(
        shap_app, args=(forecasts, events, values), default_timeout=45
    ).run()
    assert not app.exception and not app.error
    assert app.selectbox[0].value == "bag5"
    app.selectbox[2].set_value(46).run()
    assert not app.exception
    assert events.groupby("model").event_id.nunique().to_dict() == {"r0": 3, "bag5": 3, "track": 3}
    assert (folder / "shap.json").is_file()
    bad = events.copy()
    bad.loc[0, "margin"] += 0.1
    with pytest.raises(ValueError, match="additivity"):
        validate(bad, values, forecasts)
    bad = forecasts.copy()
    bad.loc[bad.event_id.eq(events.iloc[0].event_id), "raw_r0"] += 0.1
    with pytest.raises(ValueError, match="published forecast"):
        validate(events, values, bad)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["files"]["forecasts.parquet"]

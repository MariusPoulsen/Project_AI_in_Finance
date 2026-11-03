"""The app scores events live only with saved models that reproduce the published forecasts."""

import json

import numpy as np
import pandas as pd
import pytest
import xgboost as xgb

from structural_break.services import live_scoring


def _saved(tmp_path, *, shift: float = 0.0, schema: str = live_scoring.SCHEMA):
    rng = np.random.default_rng(5)
    x = pd.DataFrame({"x1": rng.normal(size=200), "x2": rng.normal(size=200)})
    y = (x.x1 + rng.normal(size=200) > 0.8).astype(int)
    (tmp_path / "live").mkdir()
    seeds = [42, 43, 44]
    margins = []
    for seed in seeds:
        model = xgb.XGBClassifier(n_estimators=10, max_depth=2, random_state=seed, subsample=0.8)
        model.fit(x, y)
        model.get_booster().save_model(tmp_path / f"live/bag5-2024-{seed}.ubj")
        margins.append(model.predict(x, output_margin=True))
    raw = (1 / (1 + np.exp(-np.stack(margins)))).mean(axis=0)
    slope, intercept = 1.1, 0.1
    probability = 1 / (1 + np.exp(-(slope * np.log(raw / (1 - raw)) + intercept)))
    ids = [f"e{i}" for i in range(200)]
    x.assign(event_id=ids, year=2024).to_parquet(tmp_path / "live/inputs.parquet", index=False)
    forecasts = pd.DataFrame(
        {"event_id": ids, "year": 2024, "raw_bag5": raw, "p_bag5": probability + shift}
    )
    metadata = {
        "schema_version": schema,
        "model": "bag5",
        "xgboost_version": xgb.__version__,
        "forecast_sha256": "abc",
        "years": [2024],
        "columns": ["x1", "x2"],
        "seeds": seeds,
        "calibration": {"2024": [slope, intercept]},
    }
    (tmp_path / "live.json").write_text(json.dumps(metadata), encoding="utf-8")
    return {"files": {"forecasts.parquet": "abc"}}, forecasts


def test_saved_models_reproduce_and_explain_the_published_forecasts(tmp_path):
    manifest, forecasts = _saved(tmp_path)
    model = live_scoring.load(tmp_path, manifest, forecasts)
    row = model.inputs.iloc[[3]]
    score = model.score(2024, row)
    assert np.isclose(score.probability[0], forecasts.p_bag5.iloc[3], atol=1e-6)
    # TreeSHAP averaged over the seed models adds up to the averaged margin.
    assert np.isclose(score.base[0] + score.contributions[0].sum(), score.margin[0], atol=1e-4)
    changed = row.assign(x1=row.x1 + 3)
    assert model.score(2024, changed).probability[0] != score.probability[0]
    with pytest.raises(ValueError, match="No saved model"):
        model.score(2023, row)


def test_loading_refuses_models_that_do_not_match_the_published_forecasts(tmp_path):
    manifest, forecasts = _saved(tmp_path, shift=0.01)
    with pytest.raises(ValueError, match="do not reproduce"):
        live_scoring.load(tmp_path, manifest, forecasts)


@pytest.mark.parametrize("change", ["schema", "binding"])
def test_loading_refuses_a_foreign_schema_or_binding(tmp_path, change):
    manifest, forecasts = _saved(tmp_path, schema="other" if change == "schema" else "live-bag5-v1")
    if change == "binding":
        manifest = {"files": {"forecasts.parquet": "different"}}
    with pytest.raises(ValueError, match="do not match"):
        live_scoring.load(tmp_path, manifest, forecasts)

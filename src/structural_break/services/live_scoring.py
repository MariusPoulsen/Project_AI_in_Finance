"""Score final-test events live with the saved bagged models (no fitting in the app).

``scripts/export_live_models.py`` saves the five seed models of the pre-registered bagged
B+rule+ou forecaster for each final-test year, the events' inputs and each year's
calibration. Loading re-scores every saved event and refuses to continue unless the
result reproduces the published raw and calibrated probabilities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCHEMA = "live-bag5-v1"


def _expit(x: np.ndarray) -> np.ndarray:
    return np.asarray(1 / (1 + np.exp(-x)), dtype=float)


def _logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-9, 1 - 1e-9)
    return np.asarray(np.log(q / (1 - q)), dtype=float)


@dataclass(frozen=True)
class Score:
    """Scores of one or more events, with TreeSHAP averaged over the seed models."""

    raw: np.ndarray
    probability: np.ndarray
    base: np.ndarray
    margin: np.ndarray
    contributions: np.ndarray


@dataclass(frozen=True)
class LiveModel:
    columns: list[str]
    boosters: dict[int, list[Any]]
    calibration: dict[int, tuple[float, float]]
    inputs: pd.DataFrame

    @property
    def years(self) -> tuple[int, ...]:
        return tuple(sorted(self.boosters))

    def score(self, year: int, x: pd.DataFrame) -> Score:
        import xgboost as xgb

        if year not in self.boosters:
            raise ValueError(f"No saved model for {year}")
        matrix = xgb.DMatrix(x[self.columns].astype(float), feature_names=self.columns)
        boosters = self.boosters[year]
        margins = np.stack([b.predict(matrix, output_margin=True) for b in boosters])
        shap = np.mean([b.predict(matrix, pred_contribs=True) for b in boosters], axis=0)
        raw = _expit(margins).mean(axis=0)
        slope, intercept = self.calibration[year]
        return Score(
            raw=raw,
            probability=_expit(slope * _logit(raw) + intercept),
            base=shap[:, -1],
            margin=margins.mean(axis=0),
            contributions=shap[:, :-1],
        )

    def event(self, event_id: str) -> pd.Series | None:
        rows = self.inputs.loc[self.inputs.event_id.eq(event_id)]
        return None if rows.empty else rows.iloc[0]


def load(root: Path, manifest: dict[str, Any], forecasts: pd.DataFrame) -> LiveModel:
    """The saved models, checked to reproduce every published final-test forecast."""
    import xgboost as xgb

    metadata = json.loads((root / "live.json").read_text(encoding="utf-8"))
    if (
        metadata["schema_version"] != SCHEMA
        or metadata["forecast_sha256"] != manifest["files"]["forecasts.parquet"]
        or metadata["xgboost_version"].split(".")[0] != xgb.__version__.split(".")[0]
    ):
        raise ValueError("Saved models do not match the published forecasts or library")
    boosters: dict[int, list[Any]] = {}
    for year in metadata["years"]:
        boosters[int(year)] = []
        for seed in metadata["seeds"]:
            booster = xgb.Booster()
            booster.load_model(root / f"live/bag5-{year}-{seed}.ubj")
            boosters[int(year)].append(booster)
    calibration = {int(y): (float(a), float(b)) for y, (a, b) in metadata["calibration"].items()}
    inputs = pd.read_parquet(root / "live/inputs.parquet")
    model = LiveModel(list(metadata["columns"]), boosters, calibration, inputs)
    published = forecasts.set_index("event_id")
    for year in model.years:
        part = inputs.loc[inputs.year.eq(year)]
        if set(part.event_id) != set(published.index[published.year.eq(year)]):
            raise ValueError(f"Saved {year} inputs do not cover the published events")
        scored = model.score(year, part)
        expected = published.loc[part.event_id]
        if not np.allclose(scored.raw, expected.raw_bag5, atol=1e-6) or not np.allclose(
            scored.probability, expected.p_bag5, atol=1e-6
        ):
            raise ValueError(f"Saved {year} models do not reproduce the published forecasts")
    return model

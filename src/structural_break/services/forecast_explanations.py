"""Validate saved TreeSHAP against the exact current walk-forward predictions."""

from __future__ import annotations

import numpy as np
import pandas as pd

SEEDS = {"r0": 1, "bag5": 5, "track": 5}


def validate(events: pd.DataFrame, values: pd.DataFrame, forecasts: pd.DataFrame) -> None:
    keys = ["model", "event_id", "seed"]
    if events.empty or values.empty or events.duplicated(keys).any():
        raise ValueError("Empty or duplicate SHAP event records")
    if values.duplicated([*keys, "feature"]).any():
        raise ValueError("Duplicate SHAP feature records")
    if set(events.model) - SEEDS.keys():
        raise ValueError("Unsupported SHAP model identity")
    if not np.isfinite(events[["base", "margin", "raw_probability"]].to_numpy(float)).all():
        raise ValueError("Nonfinite SHAP totals")
    if not np.isfinite(values.contribution.to_numpy(float)).all():
        raise ValueError("Nonfinite SHAP contributions")
    totals = values.groupby(keys).contribution.sum()
    expected = events.set_index(keys)
    if set(totals.index) != set(expected.index):
        raise ValueError("SHAP values and totals have different event/component identities")
    if not np.allclose(
        expected.margin - expected.base, totals.reindex(expected.index), atol=1e-4, rtol=1e-5
    ):
        raise ValueError("SHAP additivity check failed")
    probabilities = 1 / (1 + np.exp(-events.margin.to_numpy(float)))
    if not np.allclose(probabilities, events.raw_probability, atol=1e-6, rtol=1e-6):
        raise ValueError("SHAP margin does not reproduce the seed probability")
    published = forecasts.set_index("event_id")
    if forecasts.event_id.duplicated().any():
        raise ValueError("Duplicate current forecast IDs")
    for (model, event_id), part in events.groupby(["model", "event_id"]):
        if event_id not in published.index or len(part) != SEEDS[str(model)]:
            raise ValueError("Missing SHAP event or ensemble components")
        if set(part.seed) != set(range(42, 42 + SEEDS[str(model)])):
            raise ValueError("Unexpected SHAP seed identities")
        original = published.loc[str(event_id)]
        if not part.year.eq(original["year"]).all():
            raise ValueError("SHAP year differs from the current forecast")
        if not np.isclose(
            part.raw_probability.mean(), original[f"raw_{model}"], atol=1e-6, rtol=1e-6
        ):
            raise ValueError("SHAP components do not reproduce the published forecast")

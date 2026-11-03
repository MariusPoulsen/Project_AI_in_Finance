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
    # One grouped pass instead of a loop over events: the same checks, vectorised.
    groups = (
        events.groupby(["model", "event_id"])
        .agg(
            n=("seed", "size"),
            low=("seed", "min"),
            high=("seed", "max"),
            first_year=("year", "min"),
            last_year=("year", "max"),
            mean=("raw_probability", "mean"),
        )
        .reset_index()
    )
    seeds = groups.model.astype(str).map(SEEDS)
    if not groups.event_id.isin(published.index).all() or not groups.n.eq(seeds).all():
        raise ValueError("Missing SHAP event or ensemble components")
    # n equals the seed count and seeds are unique per event, so min and max fix the set.
    if not (groups.low.eq(42) & groups.high.eq(41 + seeds)).all():
        raise ValueError("Unexpected SHAP seed identities")
    original = published.loc[groups.event_id.astype(str).tolist()]
    years = original["year"].to_numpy()
    if (
        not (groups.first_year.to_numpy() == years).all()
        or not (groups.last_year.to_numpy() == years).all()
    ):
        raise ValueError("SHAP year differs from the current forecast")
    raw = np.array(
        [original[f"raw_{model}"].iat[i] for i, model in enumerate(groups.model.astype(str))],
        dtype=float,
    )
    if not np.allclose(groups["mean"].to_numpy(float), raw, atol=1e-6, rtol=1e-6):
        raise ValueError("SHAP components do not reproduce the published forecast")

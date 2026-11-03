"""Validate saved TreeSHAP against the exact current walk-forward predictions.

Schema ``current-tree-shap-v2`` explains every scored event. Seed totals (base, margin, raw
probability) are kept per seed model; the per-event contributions are averaged over the
bag's seed models and hold each event's largest effects plus one ``OTHER`` row with the sum
of the rest, so they add up exactly to the averaged margin minus the averaged base.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SCHEMA = "current-tree-shap-v2"
SEEDS = {"r0": 1, "bag5": 5, "track": 5}
OTHER = "__other__"


def validate(
    events: pd.DataFrame,
    values: pd.DataFrame,
    forecasts: pd.DataFrame,
    summary: pd.DataFrame | None = None,
) -> None:
    keys = ["model", "event_id", "seed"]
    event_keys = ["model", "event_id"]
    if events.empty or values.empty or events.duplicated(keys).any():
        raise ValueError("Empty or duplicate SHAP event records")
    if values.duplicated([*event_keys, "feature"]).any():
        raise ValueError("Duplicate SHAP feature records")
    if set(events.model) - SEEDS.keys():
        raise ValueError("Unsupported SHAP model identity")
    if not np.isfinite(events[["base", "margin", "raw_probability"]].to_numpy(float)).all():
        raise ValueError("Nonfinite SHAP totals")
    if not np.isfinite(values.contribution.to_numpy(float)).all():
        raise ValueError("Nonfinite SHAP contributions")
    # The seed-averaged contributions add up to the averaged margin minus the averaged base.
    expected = (
        events.assign(gap=events.margin - events.base).groupby(event_keys).gap.mean().sort_index()
    )
    totals = values.groupby(event_keys).contribution.sum().sort_index()
    if set(totals.index) != set(expected.index):
        raise ValueError("SHAP values and totals have different event identities")
    if not np.allclose(expected, totals.reindex(expected.index), atol=1e-4, rtol=1e-5):
        raise ValueError("SHAP additivity check failed")
    if not values.groupby(event_keys).feature.apply(lambda f: f.eq(OTHER).sum() == 1).all():
        raise ValueError("Each SHAP event needs exactly one row for the remaining inputs")
    probabilities = 1 / (1 + np.exp(-events.margin.to_numpy(float)))
    if not np.allclose(probabilities, events.raw_probability, atol=1e-6, rtol=1e-6):
        raise ValueError("SHAP margin does not reproduce the seed probability")
    published = forecasts.set_index("event_id")
    if forecasts.event_id.duplicated().any():
        raise ValueError("Duplicate current forecast IDs")
    groups = (
        events.groupby(event_keys)
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
    if summary is not None:
        explained = groups.groupby(["model", "first_year"]).size().to_dict()
        stated = summary.groupby(["model", "year"]).n.agg(["min", "max"])
        if (
            summary.duplicated(["model", "year", "feature"]).any()
            or not stated["min"].eq(stated["max"]).all()
            or stated["min"].to_dict() != explained
            or not np.isfinite(summary[["sum_abs", "sum"]].to_numpy(float)).all()
        ):
            raise ValueError("SHAP summary does not match the explained events")

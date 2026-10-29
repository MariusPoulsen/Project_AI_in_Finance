"""Rank the existing entry rules on the current forecast population; no probability fits."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

BASELINES = {"baseline0": "Baseline 0 (every divergence)", "baseline1": "Baseline 1 (ACTIVE only)"}
YEARS = {"2010–2017": (2010, 2017), "2018–2023": (2018, 2023), "2024–2025": (2024, 2025)}


def validate_flags(flags: pd.DataFrame, forecasts: pd.DataFrame) -> None:
    if (
        flags.event_id.duplicated().any()
        or forecasts.event_id.duplicated().any()
        or set(flags.event_id) != set(forecasts.event_id)
        or not pd.api.types.is_bool_dtype(flags.baseline1_eligible)
        or flags.baseline1_eligible.isna().any()
    ):
        raise ValueError(
            "Baseline eligibility must cover the exact forecast events with known flags"
        )


def metrics(forecasts: pd.DataFrame, flags: pd.DataFrame | None) -> pd.DataFrame:
    """Score all labelled events; ACTIVE is a binary rank, never a filtered population."""
    frame = forecasts.copy()
    if flags is not None:
        validate_flags(flags, forecasts)
        frame = frame.merge(flags, on="event_id", validate="one_to_one")
    frame = frame.loc[frame.labelled & frame.y.notna()]
    if not frame.y.isin([0, 1]).all():
        raise ValueError("Baseline metrics require binary reversion labels")
    rows = []
    for period, years in YEARS.items():
        part = frame.loc[frame.year.between(*years)]
        if part.empty:
            continue
        for key, label in BASELINES.items():
            if key == "baseline1" and flags is None:
                continue
            rank = (
                np.ones(len(part))
                if key == "baseline0"
                else part.baseline1_eligible.to_numpy(float)
            )
            rows.append(
                {
                    "model": key,
                    "label": label,
                    "period": period,
                    "roc_auc": float(roc_auc_score(part.y, rank))
                    if part.y.nunique() == 2
                    else np.nan,
                    "pr_auc": float(average_precision_score(part.y, rank))
                    if part.y.sum()
                    else np.nan,
                    "log_loss": np.nan,
                    "brier": np.nan,
                    "base_rate": float(part.y.mean()),
                    "n": len(part),
                    "selected_n": int(rank.sum()),
                }
            )
    return pd.DataFrame(rows)

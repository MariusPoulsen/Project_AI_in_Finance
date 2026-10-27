"""Trade selection of the adopted book (Decision 100): top 20 % per test year after the
R1, mean-crossing and cost filters, from the original Model B (R0) or a stored forecaster."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from structural_break import periods

SCORES = Path("outputs/model_b/scores.parquet")


def design_candidates(
    workspace: Path, selector: str = "R0", chosen_events: list[str] | None = None
) -> list[str]:
    """Decision 100 candidates: top 20 % per test year after the r1, cross and cost filters.

    ``selector`` "R0" is the original Model B (the book's selection); any other value
    names a stored ``outputs/book/scores__<selector>.parquet`` with a ``top20`` flag
    (Decision 110b: the best forecaster as an alternative selection).
    """
    from structural_break.book import portfolio as qp
    from structural_break.forecast import model_b as pb

    frame, _ = pb.load_data(workspace, Path("outputs/walkforward/simulation_frozen_exit.parquet"))
    year = pd.to_datetime(frame.set_index("event_id").event_date).dt.year
    scores = pd.read_parquet(SCORES)
    scores = scores[scores.variant.eq("R0_xgb_fixed")]
    r1 = set(pd.read_parquet("outputs/book/r1_events.parquet").event_id)
    cross = pd.read_parquet("outputs/book/features.parquet").set_index("event_id")[
        "state_days_since_zero_cross"
    ]
    costs = pd.read_parquet("outputs/book/cost_model_nets.parquet").set_index("event_id")
    rate = 2 * costs["rate_10m"]
    rate_year = year.reindex(rate.index)
    cost_cut = {y: np.nanquantile(rate[rate_year.eq(y - 1)], 0.8) for y in periods.scored_years()}
    chosen: list[str] = []
    if chosen_events is not None:  # Decision 110c: an explicit selection (the full model's ranking)
        chosen = list(chosen_events)
    elif selector == "R0":
        for _y, group in scores.groupby("year"):
            cut = float(np.quantile(group.loc[group.role.eq("threshold"), "score"], 0.8))
            chosen += list(group[group.role.eq("test") & (group.score >= cut)].event_id)
    else:
        alt = pd.read_parquet(f"outputs/book/scores__{selector}.parquet")
        chosen = list(alt.loc[alt.top20.astype(bool)].sort_values(["year", "event_id"]).event_id)
    cache = qp.load_cache(Path("outputs/book/requests.pkl"))
    return [
        e
        for e in chosen
        if e not in r1
        and not (cross.get(e, 0) > 120)
        and not (rate.get(e, np.inf) >= cost_cut.get(cast(int, year.get(e)), np.inf))
        and e in cache
    ]

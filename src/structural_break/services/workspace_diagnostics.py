"""Fixed-20-session registry/policy queries, without exposing superseded model scores."""

from __future__ import annotations

import numpy as np
import pandas as pd

from structural_break.services.research_application import ResearchApplicationService

HORIZON = 20
POLICY_RUNGS = {"BASELINE_0", "BASELINE_1", "MODEL_A", "MODEL_B"}


def registry_events(service: ResearchApplicationService) -> pd.DataFrame:
    source = service.data(HORIZON).events
    columns = [
        "event_id",
        "event_date",
        "pair_id",
        "leg_a",
        "leg_b",
        "business_group",
        "sector",
        "baseline1_eligible",
        "y_revert_success",
        "z_signed",
        "abs_z",
        "coint_pvalue",
        "half_life",
        "vix_level",
    ]
    result = source.reindex(columns=[c for c in columns if c in source]).copy()
    result["date"] = pd.to_datetime(result.pop("event_date"))
    if result["date"].dt.year.gt(2023).any():
        raise ValueError("Final-test registry rows are locked")
    years = result["date"].dt.year
    result["Period"] = np.select(
        [years.lt(2010), years.le(2017)],
        ["Before selection", "2010–2017 · selection"],
        default="2018–2023 · confirmation",
    )
    result["outcome"] = (
        result["y_revert_success"].map({1: "Reverted", 0: "Did not revert"}).fillna("Unknown")
    )
    return result.sort_values(["date", "event_id"]).reset_index(drop=True)


def policy_rows(service: ResearchApplicationService) -> pd.DataFrame:
    rows = service.strategy_rungs(HORIZON)
    if rows.empty:
        return rows
    return rows.loc[rows["rung"].isin(POLICY_RUNGS)].copy()


def registry_coverage(service: ResearchApplicationService) -> pd.DataFrame:
    """Annual denominators from registry fields, independent of old fitting partitions."""
    source = service.data(HORIZON).events
    years = pd.to_datetime(source["event_date"]).dt.year
    if years.gt(2023).any():
        raise ValueError("Final-test registry rows are locked")
    indicators = {
        "sentiment_both_known": "FinBERT known · both legs",
        "sec_a_metadata_coverage_unknown": "SEC metadata UNKNOWN · A",
        "sec_b_metadata_coverage_unknown": "SEC metadata UNKNOWN · B",
        "evidence_available": "Catalyst evidence available",
    }
    records = []
    for year, events in source.groupby(years):
        for field, label in indicators.items():
            if field not in events:
                continue
            values = events[field]
            records.append(
                {
                    "Year": year,
                    "Indicator": label,
                    "Events": len(events),
                    "Flagged": int(values.eq(1).sum()),
                    "Missing flag": int(values.isna().sum()),
                    "Share of all events": float(values.eq(1).sum() / len(events)),
                }
            )
    return pd.DataFrame(records)


def baseline_outcomes(service: ResearchApplicationService) -> pd.DataFrame:
    rows = policy_rows(service)
    if rows.empty:
        return rows
    return (
        rows.loc[rows.rung.isin(["BASELINE_0", "BASELINE_1"])]
        .reindex(columns=["label", "selected_n", "labelled_n", "label_success_rate", "priced_n"])
        .rename(
            columns={
                "label": "Policy",
                "selected_n": "Selected",
                "labelled_n": "Labelled",
                "label_success_rate": "Reversion share",
                "priced_n": "Priced",
            }
        )
    )

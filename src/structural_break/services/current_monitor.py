"""Monitor the current scored population, independently of frozen fitting partitions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from structural_break.intelligence.sentiment import SENTIMENT_FEATURE_COLUMNS
from structural_break.ml.features import FEATURE_FAMILIES
from structural_break.pipeline.features import EARNINGS, MOMENTUM, PEER, STATE, TRACK
from structural_break.pipeline.ou_features import OU
from structural_break.research.intelligence import METADATA_FEATURE_COLUMNS

PERIODS = {
    "Selection · 2010–2017": (2010, 2017),
    "Holdout · 2018–2023": (2018, 2023),
    "Final test · 2024–2025": (2024, 2025),
}
# Presentation stages for the coverage table. The canonical evaluation periods
# above and the annual models' actual fitting/calibration windows are unchanged.
COVERAGE_STAGES = {
    "Selection · 2010–2017": "Fit · 2010–2017",
    "Holdout · 2018–2023": "Calibration · 2018–2023",
    "Final test · 2024–2025": "Assessment · 2024–2025",
}
INPUTS = frozenset(c for columns in FEATURE_FAMILIES.values() for c in columns) | frozenset(
    (
        *METADATA_FEATURE_COLUMNS,
        *SENTIMENT_FEATURE_COLUMNS,
        "tone_aligned_contrast",
        *PEER,
        *STATE,
        *TRACK,
        *EARNINGS,
        *MOMENTUM,
        *OU,
    )
)

FEATURE_BLOCKS = {
    "Peer context": PEER,
    "Relationship state": STATE,
    "Track record": TRACK,
    "Earnings timing": EARNINGS,
    "Momentum": MOMENTUM,
    "OU prior": OU,
}


def feature_block(feature: str) -> str:
    return next(
        (name for name, fields in FEATURE_BLOCKS.items() if feature in fields), "Quantitative / SEC"
    )


COVERAGE = {
    "sentiment_both_known": "FinBERT tone known for both legs",
    "sec_a_metadata_coverage_unknown": "Leg A SEC metadata UNKNOWN",
    "sec_b_metadata_coverage_unknown": "Leg B SEC metadata UNKNOWN",
}


def period_of_year(year: int) -> str:
    for label, (first, last) in PERIODS.items():
        if first <= year <= last:
            return label
    raise ValueError("Year outside the current study")


def event_inputs(
    forecasts: pd.DataFrame, registry: pd.DataFrame, *, final_included: bool
) -> pd.DataFrame:
    """Left join input fields; missing registry rows remain in every denominator."""
    if forecasts.event_id.duplicated().any() or registry.event_id.duplicated().any():
        raise ValueError("Duplicate monitor event IDs")
    if not final_included and forecasts.year.gt(2023).any():
        raise ValueError("Final-test inputs are not included in this results export")
    frame = forecasts.copy()
    frame["period"] = frame.year.map(period_of_year)
    columns = [c for c in registry if c in INPUTS and c not in frame]
    source = registry[["event_id", *columns]].assign(registry_available=True)
    frame = frame.merge(source, on="event_id", how="left", validate="one_to_one")
    frame["registry_available"] = frame["registry_available"].eq(True)
    return frame


def cohorts(events: pd.DataFrame, *, final_included: bool) -> pd.DataFrame:
    records = []
    for period, (first, last) in PERIODS.items():
        part = events.loc[events.year.between(first, last)]
        pending = first == 2024 and not final_included
        labelled = part.loc[part.labelled & part.y.notna()]
        records.append(
            {
                "Period": period,
                "Status": "Results pending" if pending else "Exported",
                "Events": None if pending else len(part),
                "Labelled": None if pending else len(labelled),
                "Reverted": None if pending else int(labelled.y.sum()),
                "Reversion rate": float(labelled.y.mean()) if len(labelled) else None,
                "Pairs": None if pending else part.pair_id.nunique(),
                "Issuers": None if pending else pd.concat([part.leg_a, part.leg_b]).nunique(),
            }
        )
    return pd.DataFrame(records)


def events_by_year(events: pd.DataFrame) -> pd.DataFrame:
    return events.groupby(["year", "period"], as_index=False).agg(
        events=("event_id", "size"), labelled=("labelled", "sum")
    )


def coverage(events: pd.DataFrame) -> pd.DataFrame:
    records = []
    for (year, period), part in events.groupby(["year", "period"]):
        for field, label in COVERAGE.items():
            values = part.get(field, pd.Series(np.nan, index=part.index))
            # Missing metadata is UNKNOWN, never confirmed coverage.
            flagged = values.eq(1)
            if field.endswith("coverage_unknown"):
                flagged |= values.isna()
            records.append(
                {
                    "year": year,
                    "period": period,
                    "label": label,
                    "n": len(part),
                    "flagged": int(flagged.sum()),
                    "share": float(flagged.mean()),
                }
            )
    return pd.DataFrame(records)


def coverage_table(rows: pd.DataFrame) -> pd.DataFrame:
    summed = rows.groupby(["period", "label"], as_index=False).agg(
        n=("n", "sum"), flagged=("flagged", "sum")
    )
    summed["share"] = summed.flagged / summed.n
    summed["column"] = summed.period.map(COVERAGE_STAGES) + " (n=" + summed.n.astype(str) + ")"
    columns = [
        str(row.column)
        for period in PERIODS
        for row in summed.loc[summed.period.eq(period)].head(1).itertuples()
    ]
    return (
        summed.pivot(index="label", columns="column", values="share")
        .reindex(columns=columns)
        .reset_index(names="Indicator")
    )


def drift_features(events: pd.DataFrame) -> list[str]:
    return sorted(c for c in events if c in INPUTS and events[c].notna().any())


def drift(events: pd.DataFrame, feature: str) -> pd.DataFrame:
    if feature not in INPUTS:
        raise ValueError("Feature is not an approved quantitative/SEC metadata/tone input")
    records = []
    for year, part in events.groupby("year"):
        values = pd.to_numeric(part[feature], errors="coerce")
        records.append(
            {
                "year": year,
                "period": period_of_year(int(str(year))),
                "n": len(part),
                "missing_share": float(values.isna().mean()),
                **{f"p{q:02d}": float(values.quantile(q / 100)) for q in (5, 25, 50, 75, 95)},
            }
        )
    return pd.DataFrame(records)

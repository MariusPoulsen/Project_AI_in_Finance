"""Conservative SEC JSON availability bounds when its clock basis is uncertain.

Official cached SGML headers exposed mixed naive/aware JSON clock conventions.
No issuer/date heuristic chooses the favorable interpretation. UTC and New York
wall-clock candidates define an interval; only its upper bound can admit text.
Explicit nonzero offsets retain their stated zone. Filing dates never substitute
for missing acceptance times. This does not alter the immutable original P4.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from structural_break.data.sec import parse_acceptance_timestamp

ACCEPTANCE_POLICY = "sec-json-clock-upper-bound-v2"


def acceptance_bounds(raw: Any) -> tuple[datetime | None, datetime | None]:
    if raw is None or raw is pd.NA or (isinstance(raw, float) and pd.isna(raw)):
        return None, None
    parsed, _ = parse_acceptance_timestamp(raw)
    if parsed is None:
        return None, None
    stamp = (
        datetime.strptime(raw, "%Y%m%d%H%M%S")
        if len(raw) == 14 and raw.isdigit()
        else datetime.fromisoformat(raw)
    )
    if stamp.tzinfo is not None and stamp.utcoffset() != timedelta(0):
        return parsed, parsed
    clock = stamp.replace(tzinfo=None)
    eastern, _ = parse_acceptance_timestamp(clock.isoformat())
    assert eastern is not None
    utc = clock.replace(tzinfo=UTC)
    return min(utc, eastern), max(utc, eastern)


def apply_availability_bounds(filings: pd.DataFrame) -> pd.DataFrame:
    result = filings.copy()
    bounds = [acceptance_bounds(raw) for raw in result["acceptance_datetime_raw"]]
    result["acceptance_lower_bound_utc"] = pd.to_datetime(
        pd.Series([b[0] for b in bounds], index=result.index, dtype=object), utc=True
    )
    result["acceptance_upper_bound_utc"] = pd.to_datetime(
        pd.Series([b[1] for b in bounds], index=result.index, dtype=object), utc=True
    )
    result["acceptance_zone_ambiguous"] = result["acceptance_lower_bound_utc"].notna() & result[
        "acceptance_lower_bound_utc"
    ].ne(result["acceptance_upper_bound_utc"])
    result["acceptance_datetime_utc"] = result["acceptance_upper_bound_utc"]
    result["timestamp_quality_flag"] = result["timestamp_quality_flag"].where(
        ~result["acceptance_zone_ambiguous"], "CONSERVATIVE_AVAILABILITY_BOUND"
    )
    result["acceptance_policy"] = ACCEPTANCE_POLICY
    return result


def ambiguous_cutoff(filings: pd.DataFrame, security_id: str, cutoff: pd.Timestamp) -> bool:
    """An uncertain clock straddling a selection boundary cannot prove absence."""
    if "acceptance_lower_bound_utc" not in filings:
        return False
    relevant = filings.loc[
        filings["security_id"].eq(security_id)
        & filings["form"].isin(["8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A"])
    ]
    lower, upper = relevant["acceptance_lower_bound_utc"], relevant["acceptance_upper_bound_utc"]
    # Both admission and lookback-boundary ambiguity are explicit gaps. This
    # includes the periodic fallback window, rather than declaring NONE from it.
    if (lower.le(cutoff) & upper.gt(cutoff)).any():
        return True
    for days in (30, 180, 400):
        boundary = cutoff - pd.Timedelta(days=days)
        if (lower.lt(boundary) & upper.ge(boundary)).any():
            return True
    return False

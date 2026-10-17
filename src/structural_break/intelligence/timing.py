"""Narrow SEC filing-timing features from filing metadata only (DECISIONS 47).

The v2 metadata block summarises a 30-day window. These features ask a sharper
question: did either company file in the last one or three NYSE sessions before
the divergence signal, and did the company whose stock actually moved file?

A filing counts only when its conservative availability bound
(``acceptance_datetime_utc``, the upper end of its clock envelope) is at or
before the event cutoff. Session windows open at the actual close of the
session ``k`` sessions before the signal session. A filing whose envelope
straddles the cutoff, or a leg whose source inventory does not cover the
cutoff, cannot prove absence: that leg's fields are null (UNKNOWN), never zero.
No text, LLM, target or outcome is read.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

TIMING_VERSION = "sec-filing-timing-v1"
WINDOWS = (1, 3)
EIGHT_K_FORMS = frozenset({"8-K", "8-K/A"})
PERIODIC_FORMS = frozenset({"10-Q", "10-Q/A", "10-K", "10-K/A"})
CLOCK_FORMS = EIGHT_K_FORMS | PERIODIC_FORMS
EARNINGS_ITEM = "2.02"
LEG_FIELDS = ("8k_1s", "8k_3s", "earnings_3s")
TIMING_FEATURE_COLUMNS = (
    *(f"sec_{leg}_{field}" for leg in ("a", "b") for field in LEG_FIELDS),
    "sec_one_sided_8k_1s",
    "sec_one_sided_8k_3s",
    "sec_mover_filed_1s",
    "sec_mover_filed_3s",
)


def session_closes(start: date, end: date) -> pd.DatetimeIndex:
    """Actual XNYS session closes (UTC), including early closes."""
    from structural_break.data.market import session_schedule

    schedule = session_schedule(start, end)
    return pd.DatetimeIndex(schedule["data_available_at"]).sort_values()


def _window_starts(cutoffs: pd.DatetimeIndex, closes: pd.DatetimeIndex) -> dict[int, np.ndarray]:
    """Close (ns since epoch) of the session ``k`` sessions before each signal close."""
    position = closes.searchsorted(cutoffs, side="right") - 1
    if (position < max(WINDOWS)).any():
        raise ValueError("Session calendar does not cover the timing lookback")
    values = closes.to_numpy(dtype="datetime64[ns]").astype(np.int64)
    return {k: values[position - k] for k in WINDOWS}


def _leg_known(coverage: Mapping[str, Any] | None, cutoff: pd.Timestamp) -> bool:
    if coverage is None:
        return False
    earliest = coverage.get("earliest_observed_acceptance")
    return (
        coverage.get("status") == "OK"
        and coverage.get("missing_acceptance_count", 0) == 0
        and earliest is not None
        and pd.Timestamp(earliest) <= cutoff
    )


def _has_item(items: Any, item: str) -> bool:
    if items is None or (isinstance(items, float) and np.isnan(items)) or items is pd.NA:
        return False
    return item in re.findall(r"\b\d+\.\d+\b", str(items))


def filing_timing_features(
    events: pd.DataFrame,
    filings: pd.DataFrame,
    issuer_coverage: Mapping[str, Mapping[str, Any]],
    closes: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Ten fixed timing features per event; nulls mark UNKNOWN legs.

    ``events`` needs event_id, evidence_cutoff (or event_timestamp),
    leg_a_security_id, leg_b_security_id and, for the mover fields,
    abnormal_return_A_1d / abnormal_return_B_1d known at the signal close.
    ``issuer_coverage`` maps security_id to its source coverage row with the
    observed acceptance bounds used by the v2 metadata block.
    """
    required = {"event_id", "leg_a_security_id", "leg_b_security_id"}
    if not required.issubset(events.columns):
        raise ValueError(f"Timing features need columns {sorted(required)}")
    if events["event_id"].duplicated().any():
        raise ValueError("Timing features need unique event identities")
    stamp = events["evidence_cutoff"] if "evidence_cutoff" in events else events["event_timestamp"]
    cutoffs = pd.DatetimeIndex(pd.to_datetime(stamp, utc=True))
    starts = _window_starts(cutoffs, closes)
    clock = filings.loc[filings["form"].isin(CLOCK_FORMS)].copy()
    clock["accepted"] = pd.to_datetime(clock["acceptance_datetime_utc"], utc=True)
    lower = (
        clock["acceptance_lower_bound_utc"]
        if "acceptance_lower_bound_utc" in clock
        else clock["acceptance_datetime_utc"]
    )
    clock["lower"] = pd.to_datetime(lower, utc=True)
    clock["eight_k"] = clock["form"].isin(EIGHT_K_FORMS)
    clock["earnings"] = clock["form"].isin(PERIODIC_FORMS) | (
        clock["eight_k"] & clock["items"].map(lambda value: _has_item(value, EARNINGS_ITEM))
    )
    clock = clock.sort_values("accepted")
    by_security = {
        key: (
            group["accepted"].to_numpy(dtype="datetime64[ns]").astype(np.int64),
            group["lower"].to_numpy(dtype="datetime64[ns]").astype(np.int64),
            np.cumsum(group["eight_k"].to_numpy(dtype=int)),
            np.cumsum(group["earnings"].to_numpy(dtype=int)),
        )
        for key, group in clock.groupby("security_id", sort=False)
    }
    nothing = (np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0, int), np.empty(0, int))
    cutoff_ns = cutoffs.to_numpy(dtype="datetime64[ns]").astype(np.int64)
    rows: list[dict[str, float | None]] = []
    for position, event in enumerate(events.to_dict("records")):
        cutoff, cut = cutoffs[position], cutoff_ns[position]
        values: dict[str, float | None] = {}
        any_filed: dict[str, dict[int, float | None]] = {}
        for leg in ("a", "b"):
            security = event[f"leg_{leg}_security_id"]
            accepted, earliest, eight_k, earnings = by_security.get(security, nothing)
            straddles = bool(((earliest <= cut) & (accepted > cut)).any())
            if not _leg_known(issuer_coverage.get(security), cutoff) or straddles:
                for field in LEG_FIELDS:
                    values[f"sec_{leg}_{field}"] = None
                any_filed[leg] = {k: None for k in WINDOWS}
                continue
            last = int(np.searchsorted(accepted, cut, side="right"))  # admitted: [0, last)

            def count(cumulative: np.ndarray, first: int, last: int = last) -> int:
                if last <= first:
                    return 0
                return int(cumulative[last - 1] - (cumulative[first - 1] if first else 0))

            first = {
                k: int(np.searchsorted(accepted, starts[k][position], side="right"))
                for k in WINDOWS
            }
            values[f"sec_{leg}_8k_1s"] = float(count(eight_k, first[1]) > 0)
            values[f"sec_{leg}_8k_3s"] = float(count(eight_k, first[3]) > 0)
            values[f"sec_{leg}_earnings_3s"] = float(count(earnings, first[3]) > 0)
            any_filed[leg] = {k: float(last > first[k]) for k in WINDOWS}
        for k in WINDOWS:
            a, b = values[f"sec_a_8k_{k}s"], values[f"sec_b_8k_{k}s"]
            values[f"sec_one_sided_8k_{k}s"] = (
                None if a is None or b is None else float((a > 0) != (b > 0))
            )
        move_a = event.get("abnormal_return_A_1d")
        move_b = event.get("abnormal_return_B_1d")
        for k in WINDOWS:
            name = f"sec_mover_filed_{k}s"
            if move_a is None or move_b is None or pd.isna(move_a) or pd.isna(move_b):
                values[name] = None
                continue
            mover = "a" if abs(float(move_a)) >= abs(float(move_b)) else "b"
            values[name] = any_filed[mover][k]
        rows.append(values)
    result = pd.DataFrame(rows, columns=list(TIMING_FEATURE_COLUMNS))
    result.insert(0, "event_id", events["event_id"].to_numpy())
    return result

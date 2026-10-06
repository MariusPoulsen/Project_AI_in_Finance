"""A mixed SEC wire clock must never introduce text before actual acceptance."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from structural_break.research.availability import (
    acceptance_bounds,
    ambiguous_cutoff,
    apply_availability_bounds,
)


@pytest.mark.parametrize(
    ("raw", "lower", "upper"),
    [
        ("2021-07-01T17:30:00Z", "2021-07-01T17:30:00Z", "2021-07-01T21:30:00Z"),
        ("2021-01-04T17:30:00", "2021-01-04T17:30:00Z", "2021-01-04T22:30:00Z"),
        ("20210701173000", "2021-07-01T17:30:00Z", "2021-07-01T21:30:00Z"),
        ("2021-07-01T13:30:00-04:00", "2021-07-01T17:30:00Z", "2021-07-01T17:30:00Z"),
    ],
)
def test_both_plausible_utc_and_eastern_clocks_are_bounded(raw, lower, upper):
    first, last = acceptance_bounds(raw)
    assert first == pd.Timestamp(lower)
    assert last == pd.Timestamp(upper)
    assert first <= last


@pytest.mark.parametrize("raw", [None, "", pd.NA, float("nan")])
def test_missing_acceptance_is_never_replaced_by_a_date(raw):
    assert acceptance_bounds(raw) == (None, None)


@pytest.mark.parametrize("raw", [None, pd.NA, float("nan")])
def test_normalized_missing_acceptance_preserves_unknown_bounds(raw):
    frame = filings(raw)
    assert pd.isna(frame.iloc[0].acceptance_lower_bound_utc)
    assert pd.isna(frame.iloc[0].acceptance_upper_bound_utc)
    assert not frame.iloc[0].acceptance_zone_ambiguous


def filings(raw="2021-07-01T17:30:00Z"):
    return apply_availability_bounds(
        pd.DataFrame(
            [
                {
                    "security_id": "US:KO",
                    "form": "8-K",
                    "acceptance_datetime_raw": raw,
                    "acceptance_datetime_utc": pd.Timestamp("2021-07-01T17:30:00Z"),
                    "timestamp_quality_flag": "AWARE_SOURCE",
                }
            ]
        )
    )


def test_a_literal_z_cannot_admit_possibly_after_close_filing():
    frame = filings()
    cutoff = pd.Timestamp("2021-07-01T20:00:00Z")
    assert frame.iloc[0].acceptance_datetime_utc > cutoff
    assert frame.iloc[0].acceptance_zone_ambiguous
    assert ambiguous_cutoff(frame, "US:KO", cutoff)
    assert not ambiguous_cutoff(frame, "US:PEP", cutoff)
    assert not ambiguous_cutoff(frame, "US:KO", cutoff + pd.Timedelta(days=2))


def test_uncertain_lookback_boundary_cannot_prove_recent_absence():
    frame = filings()
    cutoff = pd.Timestamp("2021-07-31T20:00:00Z")
    assert ambiguous_cutoff(frame, "US:KO", cutoff)


def test_nonzero_explicit_offset_is_an_exact_declared_timestamp():
    frame = filings("2021-07-01T13:30:00-04:00")
    assert not frame.iloc[0].acceptance_zone_ambiguous
    assert frame.iloc[0].acceptance_datetime_utc == datetime(2021, 7, 1, 17, 30, tzinfo=UTC)
    assert not ambiguous_cutoff(frame, "US:KO", pd.Timestamp("2021-07-01T20:00:00Z"))

"""Bounded materialization retains the original selector's values and errors."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from structural_break.intelligence.evidence import EvidencePolicy, select_event_filings


def sources() -> pd.DataFrame:
    rows = []
    forms = ("8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "OTHER")
    for index in range(420):
        accepted = datetime(2004, 1, 1, tzinfo=UTC) + timedelta(days=index * 13)
        rows.append(
            {
                "security_id": "a" if index % 2 else "b",
                "filing_id": f"filing-{index:04d}",
                "form": forms[index % len(forms)],
                "acceptance_datetime_utc": accepted if index % 23 else None,
                "point_in_time_eligible": index % 19 != 0,
                "identity_valid_from": "2004-01-01" if index % 11 else None,
                "identity_valid_to": "2018-01-01" if index % 17 == 0 else None,
                "report_date": "2015-09-30" if index > 270 else "2004-09-30",
                "unused_identity": f"claim-{index}",
            }
        )
    frame = pd.DataFrame(rows)
    frame["acceptance_datetime_utc"] = pd.to_datetime(frame.acceptance_datetime_utc, utc=True)
    frame["point_in_time_eligible"] = frame.point_in_time_eligible.astype("boolean")
    return frame


def choose(frame: pd.DataFrame, cutoff: str, rules: EvidencePolicy | None = None) -> object:
    event = {"event_timestamp": cutoff, "evidence_cutoff": cutoff}
    return select_event_filings(event, frame, ["a", "b"], rules)


@pytest.mark.parametrize("extension", [180, 400, 800])
def test_all_training_years_match_original_row_validator(extension: int) -> None:
    frame = sources()
    original = frame.copy(deep=True)
    original["acceptance_datetime_utc"] = original.acceptance_datetime_utc.astype(object)
    rules = EvidencePolicy(periodic_extension_days=extension)
    for year in range(2006, 2020):
        cutoff = f"{year}-11-30T21:00:00Z"
        assert choose(frame, cutoff, rules) == choose(original, cutoff, rules)


@pytest.mark.parametrize("field", ["identity_valid_from", "identity_valid_to"])
@pytest.mark.parametrize("offset", [-1500, 3000])
def test_malformed_old_or_future_identity_retains_original_error_order(
    field: str, offset: int
) -> None:
    frame = sources().iloc[:2].copy()
    frame.loc[0, "acceptance_datetime_utc"] = pd.Timestamp("2015-01-01T21:00:00Z") + pd.Timedelta(
        days=offset
    )
    frame.loc[0, "point_in_time_eligible"] = True
    frame.loc[0, field] = "not-a-date"
    original = frame.copy()
    original["acceptance_datetime_utc"] = original.acceptance_datetime_utc.astype(object)
    if offset < 0:
        with pytest.raises(ValueError) as old:
            choose(original, "2015-01-01T21:00:00Z")
        with pytest.raises(type(old.value)) as new:
            choose(frame, "2015-01-01T21:00:00Z")
        assert str(old.value) == str(new.value)
    else:
        assert choose(frame, "2015-01-01T21:00:00Z") == choose(original, "2015-01-01T21:00:00Z")


@pytest.mark.parametrize("value", [1, "True", None, pd.NA])
def test_non_boolean_eligibility_is_never_coerced_into_true(value: object) -> None:
    frame = sources().iloc[:2].copy()
    frame["point_in_time_eligible"] = pd.Series([value, True], dtype=object)
    frame.loc[0, "acceptance_datetime_utc"] = pd.Timestamp("2015-01-01T21:00:00Z")
    original = frame.copy()
    original["acceptance_datetime_utc"] = original.acceptance_datetime_utc.astype(object)
    assert choose(frame, "2015-01-02T21:00:00Z") == choose(original, "2015-01-02T21:00:00Z")

from datetime import date

import pandas as pd

from structural_break.app_ui.lookup import find


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "pair": ["KO__PEP", "KO__PEP", "V__MA"],
            "date": pd.to_datetime(["2012-03-05", "2019-07-01", "2015-01-02"]),
        }
    )


def test_finds_the_most_recent_event_on_or_before_the_date():
    found = find(_events(), "KO__PEP", date(2020, 1, 1))
    assert found.event is not None and found.event["event_id"] == "e2"
    assert "184 days earlier" in found.message


def test_an_event_on_the_date_itself_counts():
    found = find(_events(), "KO__PEP", date(2012, 3, 5))
    assert found.event is not None and found.event["event_id"] == "e1"
    assert "on that day" in found.message


def test_a_date_before_the_first_event_says_when_the_first_one_was():
    found = find(_events(), "KO__PEP", date(2011, 1, 1))
    assert found.event is None and "05 Mar 2012" in found.message


def test_invalid_input_is_rejected_with_a_reason():
    events = _events()
    assert "listed pairs" in find(events, None, date(2020, 1, 1)).message
    assert "listed pairs" in find(events, "XX__YY", date(2020, 1, 1)).message
    assert "Enter a date" in find(events, "KO__PEP", None).message
    assert "between" in find(events, "KO__PEP", date(2030, 1, 1)).message
    assert "between" in find(events, "KO__PEP", date(2005, 1, 1)).message

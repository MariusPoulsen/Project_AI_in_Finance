"""Offline checks for the frozen outcome-blind Gemma coverage pilot."""

import copy
from typing import Any

import pandas as pd
import pytest

from structural_break.research.scheduling import build_catalyst_schedule


def inventory() -> tuple[pd.DataFrame, pd.DataFrame]:
    pairs = pd.DataFrame(
        [
            {"pair_id": f"pair-{group}", "business_group": f"business-{group:02d}"}
            for group in range(40)
        ]
    )
    events = pd.DataFrame(
        [
            {
                "event_id": f"{year}-{group}-{month}",
                "pair_id": f"pair-{group}",
                "event_timestamp": f"{year}-{month:02d}-15T21:00:00Z",
            }
            for year in range(2006, 2024)
            for group in range(40)
            for month in (1, 5, 9)
        ]
    )
    return events, pairs


def test_default_pilot_covers_years_and_groups_with_balanced_counts() -> None:
    events, pairs = inventory()
    schedule = build_catalyst_schedule(events, pairs)
    assert schedule["selected_event_count"] == 500
    assert set(schedule["year_counts"]) == {str(year) for year in range(2006, 2024)}
    assert set(schedule["business_group_counts"]) == set(pairs.business_group)
    assert max(schedule["year_counts"].values()) - min(schedule["year_counts"].values()) <= 1
    assert (
        max(schedule["business_group_counts"].values())
        - min(schedule["business_group_counts"].values())
        <= 1
    )
    assert schedule["unrepresented_years"] == schedule["unrepresented_business_groups"] == []
    assert schedule["missing_development_years"] == []
    assert schedule["policy"]["call_budget_including_retries"] == 1000
    assert schedule["selected_event_count"] * (1 + schedule["policy"]["max_retries"]) <= 1000
    assert schedule["outcomes_or_scores_read"] is False
    selected = events.set_index("event_id").loc[schedule["selected_event_ids"]]
    assert selected.event_timestamp.is_monotonic_increasing


def test_schedule_is_invariant_to_input_order_and_reconstructed_offline() -> None:
    events, pairs = inventory()
    expected = build_catalyst_schedule(events, pairs)
    actual = build_catalyst_schedule(
        events.sample(frac=1, random_state=3), pairs.sample(frac=1, random_state=9)
    )
    assert actual == expected
    assert len(expected["selected_event_ids"]) == len(set(expected["selected_event_ids"]))
    changed = events.copy()
    changed.loc[0, "event_timestamp"] = "2006-02-15T21:00:00Z"
    assert build_catalyst_schedule(changed, pairs)["schedule_sha256"] != expected["schedule_sha256"]


@pytest.mark.parametrize("column", ["target", "y_revert_success", "score", "raw_probability"])
def test_scheduler_rejects_targets_and_scores(column: str) -> None:
    events, pairs = inventory()
    events[column] = 1
    with pytest.raises(ValueError, match="identities/timestamps only"):
        build_catalyst_schedule(events, pairs)


def test_sparse_year_group_cells_are_disclosed_and_do_not_starve_rare_groups() -> None:
    events, pairs = inventory()
    keep = events.event_id.str.endswith("-0-1") | events.event_id.eq("2023-39-1")
    events = events.loc[keep].copy()
    schedule = build_catalyst_schedule(events, pairs)
    assert schedule["selected_event_count"] == 19
    assert schedule["business_group_counts"]["business-39"] == 1
    assert schedule["unrepresented_business_groups"] == []
    assert schedule["eligible_event_count"] == len(events)
    assert len(schedule["missing_business_groups"]) == 38
    assert schedule["available_business_group_counts"]["business-39"] == 1
    assert all(schedule["year_counts"][str(year)] >= 1 for year in range(2006, 2024))


def test_retry_reservation_caps_pilot_and_insufficient_budget_is_visible() -> None:
    events, pairs = inventory()
    schedule = build_catalyst_schedule(events, pairs, max_events=900, max_calls=20, max_retries=1)
    assert schedule["selected_event_count"] == schedule["policy"]["effective_max_events"] == 10
    assert schedule["unrepresented_years"]
    assert schedule["unrepresented_business_groups"]
    zero = build_catalyst_schedule(events, pairs, max_calls=1, max_retries=1)
    assert zero["selected_event_ids"] == []


def test_pre_2006_rows_remain_in_inventory_but_not_pilot() -> None:
    events, pairs = inventory()
    early = events.iloc[:1].copy()
    early.loc[:, "event_id"] = "warm-up"
    early.loc[:, "event_timestamp"] = "2005-05-15T21:00:00Z"
    schedule = build_catalyst_schedule(pd.concat([events, early]), pairs)
    assert "warm-up" not in schedule["selected_event_ids"]
    assert schedule["eligible_event_count"] == len(events)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2024-01-01T00:00:00Z",
        "2023-12-31T23:30:00-02:00",
        "2003-01-01T00:00:00Z",
        "2020-01-01",
        None,
    ],
)
def test_invalid_or_final_utc_timestamps_are_blocked(timestamp: Any) -> None:
    events, pairs = inventory()
    events.loc[0, "event_timestamp"] = timestamp
    with pytest.raises(ValueError, match="development-only"):
        build_catalyst_schedule(events, pairs)


@pytest.mark.parametrize(
    "options",
    [
        {"max_events": 0},
        {"max_events": True},
        {"max_calls": 0},
        {"max_retries": -1},
        {"max_retries": True},
    ],
)
def test_invalid_limits_never_produce_a_schedule(options: dict[str, Any]) -> None:
    events, pairs = inventory()
    with pytest.raises(ValueError, match="limit"):
        build_catalyst_schedule(events, pairs, **options)


def test_fixed_peer_group_changes_are_bound_in_schedule_identity() -> None:
    events, pairs = inventory()
    original = build_catalyst_schedule(events, pairs)
    changed = copy.deepcopy(pairs)
    changed.loc[0, "business_group"] = "business-reclassified"
    assert (
        build_catalyst_schedule(events, changed)["pair_groups_sha256"]
        != original["pair_groups_sha256"]
    )

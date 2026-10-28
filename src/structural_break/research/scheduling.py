"""Deterministic, target-blind Gemma pilot selection across years and peer groups."""

from __future__ import annotations

import hashlib
from collections import Counter, deque
from typing import Any

import pandas as pd

from structural_break import periods
from structural_break.research.universe import json_bytes

CATALYST_SCHEDULE_VERSION = "year-business-group-balanced-gemma-pilot-v1"
DEFAULT_CATALYST_EVENTS = 500
MAX_CATALYST_CALLS = 1000
_EVENT_COLUMNS = ("event_id", "pair_id", "event_timestamp")


def _sha(value: object) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def build_catalyst_schedule(
    events: pd.DataFrame,
    pairs: pd.DataFrame,
    *,
    max_events: int = DEFAULT_CATALYST_EVENTS,
    max_calls: int = MAX_CATALYST_CALLS,
    max_retries: int = 1,
) -> dict[str, Any]:
    """Freeze selection without consulting outcomes, prices, evidence or scores.

    Cover each available 2006--2023 year first, then each business group not yet
    covered. Fill the remaining slots by the least represented year, group and
    year/group cell, in that order. Candidate events within a cell use a fixed
    hash order; selections are returned chronologically for API processing.
    The call allowance reserves every permitted retry, even if caches later
    avoid requests. Sparse cells and all unavailable margins remain disclosed.
    """
    if set(events.columns) != set(_EVENT_COLUMNS):
        raise ValueError("Catalyst scheduling accepts event identities/timestamps only")
    if events.empty or events["event_id"].duplicated().any():
        raise ValueError("Catalyst scheduling requires nonempty unique event identities")
    if not {"pair_id", "business_group"}.issubset(pairs.columns):
        raise ValueError("Catalyst scheduling requires frozen pair business groups")
    if pairs["pair_id"].duplicated().any():
        raise ValueError("Catalyst scheduling requires unique frozen pairs")
    if any(type(value) is not int or value < 1 for value in (max_events, max_calls)):
        raise ValueError("Catalyst pilot event/call limits must be positive integers")
    if type(max_retries) is not int or not 0 <= max_retries <= 5:
        raise ValueError("Catalyst pilot retry limit must be an integer from zero to five")
    call_budget = min(max_calls, MAX_CATALYST_CALLS)
    effective_limit = min(max_events, call_budget // (1 + max_retries))
    groups = pairs.loc[:, ["pair_id", "business_group"]].sort_values("pair_id")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in groups["business_group"].tolist()
    ):
        raise ValueError("Catalyst scheduling requires explicit frozen business groups")
    group_by_pair = groups.set_index("pair_id")["business_group"].to_dict()
    normalized = []
    cells: dict[tuple[int, str], deque[dict[str, Any]]] = {}
    for source in events.to_dict("records"):
        if (
            any(
                not isinstance(source[field], str) or not source[field].strip()
                for field in ("event_id", "pair_id")
            )
            or source["pair_id"] not in group_by_pair
        ):
            raise ValueError("Catalyst event identity is outside the frozen universe")
        timestamp = pd.Timestamp(source["event_timestamp"])
        if pd.isna(timestamp) or timestamp.tzinfo is None:
            raise ValueError("Catalyst scheduling requires development-only aware timestamps")
        timestamp = timestamp.tz_convert("UTC")
        if not 2004 <= timestamp.year <= periods.data_end().year:
            raise ValueError("Catalyst scheduling requires development-only aware timestamps")
        row = {
            "event_id": source["event_id"],
            "pair_id": source["pair_id"],
            "event_timestamp": timestamp.isoformat(),
        }
        normalized.append(row)
        if timestamp.year >= 2006:
            key = (timestamp.year, group_by_pair[source["pair_id"]])
            cells.setdefault(key, deque()).append(row)
    normalized.sort(key=lambda row: (row["event_timestamp"], row["pair_id"], row["event_id"]))
    for key, queue in cells.items():
        cells[key] = deque(
            sorted(
                queue,
                key=lambda row: (
                    _sha([CATALYST_SCHEDULE_VERSION, row]),
                    row["event_id"],
                ),
            )
        )
    available_years = sorted({year for year, _ in cells})
    available_groups = sorted({group for _, group in cells})
    year_counts: Counter[int] = Counter()
    group_counts: Counter[str] = Counter()
    cell_counts: Counter[tuple[int, str]] = Counter()
    selected: list[dict[str, Any]] = []
    cell_order = {key: _sha([CATALYST_SCHEDULE_VERSION, *key]) for key in cells}

    def choose(candidates: list[tuple[int, str]]) -> None:
        key = min(
            candidates,
            key=lambda cell: (
                year_counts[cell[0]],
                group_counts[cell[1]],
                cell_counts[cell],
                cell_order[cell],
                cell,
            ),
        )
        selected.append(cells[key].popleft())
        year_counts[key[0]] += 1
        group_counts[key[1]] += 1
        cell_counts[key] += 1

    for year in available_years:
        if len(selected) == effective_limit:
            break
        choose([key for key, queue in cells.items() if key[0] == year and queue])
    for group in available_groups:
        if len(selected) == effective_limit:
            break
        if not group_counts[group]:
            choose([key for key, queue in cells.items() if key[1] == group and queue])
    while len(selected) < effective_limit:
        candidates = [key for key, queue in cells.items() if queue]
        if not candidates:
            break
        choose(candidates)
    selected.sort(key=lambda row: (row["event_timestamp"], row["pair_id"], row["event_id"]))
    selected_ids = [row["event_id"] for row in selected]
    available = {
        year: sum(len(queue) for (cell_year, _), queue in cells.items() if cell_year == year)
        + year_counts[year]
        for year in available_years
    }
    group_available = {
        group: sum(len(queue) for (_, cell_group), queue in cells.items() if cell_group == group)
        + group_counts[group]
        for group in available_groups
    }
    # Development schedules keep their recorded 2023 end; a final-test schedule (after the
    # owner's unlock, Decision 120a) records the year its events reach.
    end_year = max([2023, *available_years])
    body = {
        "policy": {
            "version": CATALYST_SCHEDULE_VERSION,
            "start_year": 2006,
            "end_year": end_year,
            "requested_max_events": max_events,
            "call_budget_including_retries": call_budget,
            "max_retries": max_retries,
            "effective_max_events": effective_limit,
            "selection": "year_coverage_group_coverage_then_least_year_group_cell",
            "within_cell_order": "sha256_version_and_allowlisted_event",
            "processing_order": "event_timestamp_pair_id_event_id",
        },
        "events_sha256": _sha(normalized),
        "pair_groups_sha256": _sha(groups.to_dict("records")),
        "selected_event_ids": selected_ids,
        "selected_events_sha256": _sha(selected),
        "selected_event_count": len(selected),
        "eligible_event_count": sum(available.values()),
        "year_counts": {str(year): year_counts[year] for year in available_years},
        "business_group_counts": {group: group_counts[group] for group in available_groups},
        "available_year_counts": {str(year): available[year] for year in available_years},
        "available_business_group_counts": group_available,
        "unrepresented_years": [year for year in available_years if not year_counts[year]],
        "unrepresented_business_groups": [
            group for group in available_groups if not group_counts[group]
        ],
        "missing_development_years": [
            year for year in range(2006, end_year + 1) if year not in available_years
        ],
        "missing_business_groups": sorted(set(group_by_pair.values()) - set(available_groups)),
        "all_events_retained_in_feature_population": True,
        "outcomes_or_scores_read": False,
    }
    return dict(body, schedule_sha256=_sha(body))

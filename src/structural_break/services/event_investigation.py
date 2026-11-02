"""Decode an event's saved, point-in-time desk evidence without live requests."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd


def evidence_record(
    cases: pd.DataFrame, event_id: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    if cases.empty:
        return None, None, "Cached desk evidence has not been exported"
    rows = cases.loc[cases.event_id.eq(event_id)]
    if rows.empty:
        return None, None, "Not in the entry desk's region"
    if len(rows) != 1:
        raise ValueError("Duplicate desk event")
    row = rows.iloc[0]
    case, result = json.loads(row.case_json), json.loads(row.result_json)
    if case is not None:
        event = case["event"]
        if event["event_id"] != event_id:
            raise ValueError("Evidence event identity differs")
        cutoff = pd.Timestamp(event["event_timestamp"])
        chunks = {c["chunk_id"]: c for c in event["evidence"]}
        if len(chunks) != len(event["evidence"]) or any(
            pd.Timestamp(c["source_timestamp"]) > cutoff for c in chunks.values()
        ):
            raise ValueError("Duplicate or future event evidence")
        if result is not None:
            for stage in result.get("stages", {}).values():
                report = stage.get("report") or {}
                for claim in report.get("claims", []):
                    for citation in claim.get("citations", []):
                        source = chunks.get(citation["chunk_id"])
                        if source is None or citation["quote"] not in source["text"]:
                            raise ValueError("Cached claim citation does not match its source")
    return case, result, str(row.status)

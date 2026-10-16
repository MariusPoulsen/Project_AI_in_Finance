"""Fixed Model B catalyst feature block; missing evidence never drops events."""

import math
from collections.abc import Mapping, Sequence
from typing import Any, cast

import pandas as pd

from structural_break.intelligence.extraction import (
    AFFECTED_LEGS,
    DIRECTIONS,
    EVENT_TYPES,
    MATERIALITIES,
    RELEVANCES,
)

EVENT_FEATURE_SCHEMA_VERSION = "sec-event-features-v2"
_CATEGORIES = {
    "event_type": EVENT_TYPES,
    "affected_leg": AFFECTED_LEGS,
    "materiality": MATERIALITIES,
    "direction": DIRECTIONS,
    "relationship_relevance": RELEVANCES,
}


def _name(field: str, category: str) -> str:
    return f"{field}_{category.replace('&', '_AND_')}"


_ONE_HOTS = tuple(
    _name(field, category) for field, cats in _CATEGORIES.items() for category in cats
)
EVENT_FEATURE_NAMES = (
    *_ONE_HOTS,
    "one_sided_event",
    "source_count",
    "document_recency_days",
    "extraction_confidence",
    "evidence_available",
)
OPTIONAL_EVENT_FEATURE_NAMES = frozenset({"document_recency_days", "extraction_confidence"})
BINARY_EVENT_FEATURE_NAMES = frozenset((*_ONE_HOTS, "one_sided_event", "evidence_available"))


def event_schema_columns() -> list[dict[str, Any]]:
    """Ordered definitions shared by fitting and inference.

    Confidence is provider self-reported extraction certainty. It is not an
    independently calibrated probability of catalyst correctness or reversion.
    Recency is from the latest cited filing's acceptance, not its reporting date.
    """
    definitions = {
        "one_sided_event": "Only one leg has a MEDIUM/HIGH catalyst; other leg coverage complete",
        "source_count": "Number of distinct admissible supporting filing IDs, not chunks",
        "document_recency_days": "Fractional calendar days since most recent cited acceptance",
        "extraction_confidence": "Provider self-reported extraction certainty; uncalibrated",
        "evidence_available": "Usable chunks or explicitly complete empty retrieval; not success",
    }
    return [
        {
            "name": name,
            "dtype": "float64",
            "allow_missing": name in OPTIONAL_EVENT_FEATURE_NAMES,
            "binary": name in BINARY_EVENT_FEATURE_NAMES,
            "family": "event",
            "definition": definitions.get(name, "Fixed one-hot structured SEC catalyst category"),
            "lookback_rule": "bounded admissible SEC evidence selection before event cutoff",
            "lookback_sessions": None,
            "source": "validated historical SEC catalyst extraction",
            "availability_column": "event_available_at",
        }
        for name in EVENT_FEATURE_NAMES
    ]


def event_feature_schema(version: str = EVENT_FEATURE_SCHEMA_VERSION) -> dict[str, Any]:
    return {
        "version": version,
        "feature_columns": list(EVENT_FEATURE_NAMES),
        "columns": event_schema_columns(),
        "confidence_meaning": "Self-reported extraction certainty; no empirical calibration",
    }


def build_event_feature_frame(
    events: pd.DataFrame,
    extractions: pd.DataFrame | Sequence[Mapping[str, Any]],
    dataset_version: str,
) -> pd.DataFrame:
    """Exactly one fixed feature row per input event, retaining all UNKNOWNs."""
    if events["event_id"].duplicated().any():
        raise ValueError("Duplicate event IDs")
    rows: list[Mapping[str, Any]] = (
        cast(list[Mapping[str, Any]], extractions.to_dict("records"))
        if isinstance(extractions, pd.DataFrame)
        else list(extractions)
    )
    index: dict[str, Mapping[str, Any]] = {}
    for record in rows:
        identity = str(record["event_id"])
        if identity in index:
            raise ValueError("Duplicate extraction event IDs")
        index[identity] = record
    if set(index) - set(events["event_id"].astype(str)):
        raise ValueError("Extraction references an event outside this dataset")
    output = []
    for event in events.to_dict("records"):
        extraction = index.get(str(event["event_id"]))
        flags = []
        if extraction is None:
            extraction = {
                "event_type": "UNKNOWN",
                "affected_leg": "UNKNOWN",
                "materiality": "UNKNOWN",
                "direction": "UNKNOWN",
                "relationship_relevance": "UNKNOWN",
                "one_sided_event": False,
                "source_count": 0,
                "evidence_available": False,
                "document_recency_days": None,
                "extraction_confidence": None,
            }
            flags.append("EXTRACTION_MISSING_UNKNOWN")
        event_time = pd.Timestamp(event["event_timestamp"])
        if "pair_id" in extraction and extraction["pair_id"] != event["pair_id"]:
            raise ValueError("Extraction pair does not match event")
        if "event_timestamp" in extraction:
            if pd.Timestamp(extraction["event_timestamp"]) != event_time:
                raise ValueError("Extraction timestamp does not match event")
        cutoff = pd.Timestamp(extraction.get("evidence_cutoff", event_time))
        if event_time.tzinfo is None or cutoff.tzinfo is None or cutoff > event_time:
            raise ValueError("Event feature cutoff is invalid or after event")
        result: dict[str, Any] = {
            "event_id": event["event_id"],
            "pair_id": event["pair_id"],
            "event_timestamp": event_time,
            "dataset_version": dataset_version,
            "event_feature_schema_version": EVENT_FEATURE_SCHEMA_VERSION,
            "event_available_at": cutoff,
        }
        for field, categories in _CATEGORIES.items():
            value = extraction.get(field, "UNKNOWN")
            if value not in categories:
                raise ValueError(f"Unknown extraction category: {field}")
            result.update(
                {_name(field, category): float(value == category) for category in categories}
            )
        for field in (
            "one_sided_event",
            "source_count",
            "document_recency_days",
            "extraction_confidence",
            "evidence_available",
        ):
            value = extraction.get(field)
            number = float(value) if value is not None else float("nan")
            if not math.isfinite(number):
                if field not in OPTIONAL_EVENT_FEATURE_NAMES:
                    raise ValueError(f"Required event feature is missing: {field}")
                if math.isinf(number):
                    raise ValueError(f"Infinite event feature: {field}")
            elif number < 0:
                raise ValueError(f"Event feature is negative: {field}")
            elif field in {"one_sided_event", "evidence_available"} and number not in {0, 1}:
                raise ValueError(f"Invalid binary event feature: {field}")
            elif field == "source_count" and not number.is_integer():
                raise ValueError("Source count must be integer")
            elif field == "extraction_confidence" and number > 1:
                raise ValueError("Extraction confidence exceeds one")
            result[field] = number
        if extraction.get("event_type") == "UNKNOWN":
            flags.extend(extraction.get("reason_codes", ["EVIDENCE_OR_EXTRACTION_UNKNOWN"]))
        result["quality_flags"] = sorted(set(flags))
        output.append(result)
    return pd.DataFrame(
        output,
        columns=[
            "event_id",
            "pair_id",
            "event_timestamp",
            "dataset_version",
            "event_feature_schema_version",
            "event_available_at",
            *EVENT_FEATURE_NAMES,
            "quality_flags",
        ],
    )

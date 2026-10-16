"""The fixed event block preserves rows and makes missing coverage explicit."""

from typing import Any

import numpy as np
import pandas as pd
import pytest

from structural_break.intelligence.event_features import (
    BINARY_EVENT_FEATURE_NAMES,
    EVENT_FEATURE_NAMES,
    OPTIONAL_EVENT_FEATURE_NAMES,
    build_event_feature_frame,
    event_feature_schema,
)


def events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": f"event_{index}",
                "pair_id": "KO__PEP",
                "event_timestamp": pd.Timestamp("2022-01-01T21:00:00Z"),
                "y_revert_success": index % 2,
            }
            for index in range(2)
        ]
    )


def extracted(**kwargs: Any) -> dict[str, Any]:
    return {
        "event_id": "event_0",
        "event_type": "EARNINGS",
        "affected_leg": "A",
        "materiality": "MEDIUM",
        "direction": "POSITIVE",
        "relationship_relevance": "INDIRECT",
        "one_sided_event": True,
        "source_count": 2,
        "document_recency_days": 4.5,
        "extraction_confidence": 0.8,
        "evidence_available": True,
        **kwargs,
    }


def test_fixed_schema_and_missing_retention() -> None:
    frame = build_event_feature_frame(events(), [extracted()], "version1")
    assert len(frame) == 2
    assert frame.iloc[0]["event_type_EARNINGS"] == 1
    assert frame.iloc[1]["event_type_UNKNOWN"] == 1
    assert frame.iloc[1]["evidence_available"] == 0
    assert np.isnan(frame.iloc[1]["document_recency_days"])
    assert np.isnan(frame.iloc[1]["extraction_confidence"])
    assert frame.iloc[1]["source_count"] == 0
    assert "y_revert_success" not in frame
    schema = event_feature_schema()
    assert schema["feature_columns"] == list(EVENT_FEATURE_NAMES)
    assert {column["name"] for column in schema["columns"] if column["allow_missing"]} == (
        OPTIONAL_EVENT_FEATURE_NAMES
    )
    for name in BINARY_EVENT_FEATURE_NAMES:
        assert set(frame[name]) <= {0, 1}


def test_none_and_unknown_are_different_features() -> None:
    none = extracted(
        event_type="NONE",
        affected_leg="NONE",
        direction="UNKNOWN",
        materiality="UNKNOWN",
        relationship_relevance="NONE",
        one_sided_event=False,
        source_count=0,
        document_recency_days=None,
        extraction_confidence=None,
    )
    frame = build_event_feature_frame(events(), [none], "test")
    assert frame.iloc[0]["event_type_NONE"] == 1 and frame.iloc[0]["evidence_available"] == 1
    assert frame.iloc[1]["event_type_UNKNOWN"] == 1 and frame.iloc[1]["evidence_available"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("materiality", "invented"),
        ("source_count", -1),
        ("source_count", 1.5),
        ("evidence_available", 2),
        ("extraction_confidence", 1.5),
    ],
)
def test_feature_contract_rejects_invalid(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        build_event_feature_frame(events(), [extracted(**{field: value})], "test")


def test_future_cutoff_rejected() -> None:
    with pytest.raises(ValueError, match="cutoff"):
        build_event_feature_frame(
            events(), [extracted(evidence_cutoff="2022-01-02T21:00:00Z")], "test"
        )


def test_duplicate_and_unmatched_extractions_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate extraction"):
        build_event_feature_frame(events(), [extracted(), extracted()], "test")
    with pytest.raises(ValueError, match="outside"):
        build_event_feature_frame(events(), [extracted(event_id="not_present")], "test")


def test_empty_events_schema_and_dataframe_input() -> None:
    frame = build_event_feature_frame(events().iloc[:0], pd.DataFrame(), "test")
    assert frame.empty and set(EVENT_FEATURE_NAMES) <= set(frame.columns)
    other = build_event_feature_frame(events(), pd.DataFrame([extracted()]), "test")
    assert len(other) == 2

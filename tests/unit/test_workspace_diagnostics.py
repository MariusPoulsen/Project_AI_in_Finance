"""Registry diagnostics retain full denominators and the final-test boundary."""

from types import SimpleNamespace

import pandas as pd
import pytest

from structural_break.services.workspace_diagnostics import registry_coverage


def test_source_flags_retain_unknowns_in_annual_denominator():
    events = pd.DataFrame(
        {
            "event_date": ["2018-01-02", "2018-01-03", "2018-01-04"],
            "sentiment_both_known": [1, 0, None],
        }
    )
    service = SimpleNamespace(data=lambda horizon: SimpleNamespace(events=events))
    row = registry_coverage(service).iloc[0]
    assert row["Events"] == 3 and row["Flagged"] == 1 and row["Missing flag"] == 1
    assert row["Share of all events"] == pytest.approx(1 / 3)


def test_registry_coverage_cannot_expose_final_test_inputs():
    events = pd.DataFrame({"event_date": ["2024-01-02"], "sentiment_both_known": [1]})
    service = SimpleNamespace(data=lambda horizon: SimpleNamespace(events=events))
    with pytest.raises(ValueError, match="locked"):
        registry_coverage(service)

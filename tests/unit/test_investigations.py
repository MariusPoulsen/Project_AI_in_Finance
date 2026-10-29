"""Scientific bindings and shareable investigations, with no external requests."""

import json

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from structural_break.agents.desk_runner import walk_forward
from structural_break.services import current_monitor, full_explanations
from structural_break.services.event_investigation import evidence_record


def stack_fixture():
    rng = np.random.default_rng(5557)
    n = 660
    frame = pd.DataFrame(
        {
            "event_id": [f"event-{i}" for i in range(n)],
            "year": np.repeat([2010, 2011, 2012], 220),
            "base_score": rng.uniform(0.03, 0.8, n),
            "y": rng.integers(0, 2, n),
        }
    )
    for field in full_explanations.AGENT_FEATURES:
        frame[field] = rng.integers(0, 5, n)
    forecasts = frame[["event_id", "year"]].copy()
    forecasts["p_full"] = walk_forward(frame, True, "base_score")
    forecasts["p_full_base"] = walk_forward(frame, False, "base_score")
    return frame, forecasts


def test_linear_explanations_reproduce_the_native_annual_stack_and_fail_on_tampering():
    frame, forecasts = stack_fixture()
    totals, values = full_explanations.reconstruct(frame)
    full_explanations.validate(totals, values, forecasts)
    values.loc[0, "contribution"] += 0.1
    with pytest.raises(ValueError, match="additivity"):
        full_explanations.validate(totals, values, forecasts)


def test_later_outcomes_cannot_change_an_earlier_explanation():
    frame, _ = stack_fixture()
    before, _ = full_explanations.reconstruct(frame)
    frame.loc[frame.year.eq(2012), "y"] = 1 - frame.loc[frame.year.eq(2012), "y"]
    after, _ = full_explanations.reconstruct(frame)
    pd.testing.assert_frame_equal(before.loc[before.year.eq(2011)], after.loc[after.year.eq(2011)])


def test_full_input_export_includes_engineered_values_but_excludes_catalysts_and_outcomes():
    registry = pd.DataFrame(
        {
            "event_id": ["a", "b"],
            "peer_gap_aligned_z": [0.1, 0.2],
            "ou_p_label": [0.3, 0.4],
            "track_pair_rate": [0.2, np.nan],
            "affected_leg_A": [1, 0],
            "y_revert_success": [1, 0],
        }
    )
    forecasts = pd.DataFrame({"event_id": ["a", "b"], "year": [2010, 2018]})
    joined = current_monitor.event_inputs(forecasts, registry, final_included=False)
    assert joined.registry_available.all()
    assert set(current_monitor.drift_features(joined)) == {
        "peer_gap_aligned_z",
        "ou_p_label",
        "track_pair_rate",
    }
    assert "affected_leg_A" not in joined and "y_revert_success" not in joined
    assert current_monitor.feature_block("ou_p_label") == "OU prior"


def case_frame(stamp="2018-01-01T20:00:00Z", quote="Known words"):
    case = {
        "event": {
            "event_id": "e",
            "event_timestamp": "2018-01-01T21:00:00Z",
            "evidence": [{"chunk_id": "c", "source_timestamp": stamp, "text": "Known words"}],
        }
    }
    result = {
        "stages": {
            "analyst": {"report": {"claims": [{"citations": [{"chunk_id": "c", "quote": quote}]}]}}
        }
    }
    return pd.DataFrame(
        {
            "event_id": ["e"],
            "status": ["CASE"],
            "case_json": [json.dumps(case)],
            "result_json": [json.dumps(result)],
        }
    )


def test_event_evidence_rejects_future_sources_and_wrong_quotes():
    assert evidence_record(case_frame(), "e")[0] is not None
    with pytest.raises(ValueError, match="future"):
        evidence_record(case_frame(stamp="2018-01-02T20:00:00Z"), "e")
    with pytest.raises(ValueError, match="citation"):
        evidence_record(case_frame(quote="Invented words"), "e")
    assert evidence_record(case_frame(), "missing")[0] is None


def link_controls():
    from structural_break.app_ui import navigation

    navigation.year_range(2010, 2023)
    navigation.multiselect("Group", ["Retail", "Banks"], "scan_group")
    navigation.probability()
    navigation.text_input("Pair", "scan_pair")
    navigation.toggle("Traded", "scan_traded", help="Saved entry")
    navigation.selectbox("Model", ["p_r0", "p_full"], "scan_model", default="p_r0")


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
@pytest.mark.usefixtures("preserve_main_module")
def test_shared_filters_hydrate_and_update_and_invalid_values_fall_back():
    app = AppTest.from_function(link_controls, default_timeout=30)
    app.query_params.update(
        {
            "scan_years": "2018:2021",
            "scan_group": ["Retail", "Banks"],
            "scan_min": "0.23",
            "scan_pair": "KO",
            "scan_traded": "1",
            "scan_model": "p_full",
        }
    )
    app.run()
    assert not app.exception
    assert app.slider[0].value == (2018, 2021)
    assert app.multiselect[0].value == ["Retail", "Banks"]
    assert app.slider[1].value == 0.23 and app.toggle[0].value
    app.text_input[0].set_value("AEO").run()
    assert app.query_params["scan_pair"] == ["AEO"]
    app.query_params.update(
        {"scan_years": "2025:2010", "scan_min": "broken", "scan_model": "unknown"}
    )
    app.run()
    assert not app.exception
    assert app.slider[0].value == (2022, 2023) and app.slider[1].value == 0
    assert app.selectbox[0].value == "p_r0"

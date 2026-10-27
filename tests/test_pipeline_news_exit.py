from datetime import UTC, datetime

import numpy as np
import pandas as pd

from structural_break.pipeline import news_exit as e2


def _table() -> pd.DataFrame:
    rows = [("US:A", f"2015-0{m}-10 12:00", False, 0.05, 0.3) for m in range(1, 6)]
    rows += [
        ("US:A", "2015-06-02 12:00", True, 0.6, -0.5),
        ("US:A", "2015-06-03 12:00", False, 0.1, 0.1),
    ]
    return pd.DataFrame(
        rows, columns=["security_id", "acceptance_datetime_utc", "earnings", "negative", "net"]
    ).assign(
        acceptance_datetime_utc=lambda f: pd.to_datetime(f["acceptance_datetime_utc"], utc=True)
    )


def test_entry_evidence_uses_mover_windows_surprise_and_volume() -> None:
    frame = pd.DataFrame(
        {
            "pair_id": ["A__B"],
            "event_timestamp": ["2015-06-03T20:00:00+00:00"],
            "abnormal_return_A_1d": [-0.05],
            "abnormal_return_B_1d": [0.01],
        }
    )
    pairs = pd.DataFrame(
        {"pair_id": ["A__B"], "leg_a_security_id": ["US:A"], "leg_b_security_id": ["US:B"]}
    )
    evidence = e2.entry_evidence(frame, pairs, e2.headline_index(_table())).iloc[0]
    assert evidence["h_neg_1s"] == 0.1 and evidence["h_neg_3s"] == 0.6
    assert evidence["h_count_5s"] == 2
    assert np.isclose(evidence["h_surprise_3s"], -0.5 - 0.3)


def test_sizing_contrast_scales_losses_by_weight() -> None:
    frame = pd.DataFrame(
        {
            "event_date": pd.date_range("2010-01-01", periods=12, freq="MS").date,
            "frozen|status": "COMPLETE",
            "frozen|net": [-0.01] * 6 + [0.002] * 6,
            "baseline1_eligible": True,
            "mover_tone_negative": [0.5] * 6 + [np.nan] * 6,
        }
    )
    result = e2.sizing_contrast(frame, "Z1_recent_tone_weight", "B0", (2006, 2015))
    assert np.isclose(result["estimate_bps"], 50.0) and result["reduced_share"] == 0.5


def test_news_times_are_after_the_signal_and_within_the_horizon() -> None:
    rows = e2.headline_index(_table())["US:A"]
    signal = datetime(2015, 6, 1, 20, tzinfo=UTC)
    times = e2._times(rows, signal, rows["negative"].ge(0.2))
    assert times == [datetime(2015, 6, 2, 12, tzinfo=UTC)]
    assert e2._times(e2.EMPTY, signal) == []


def test_record_commands_append_once(tmp_path) -> None:
    import json

    out = tmp_path / "out"
    out.mkdir()
    choice = {
        "name": "E5_timeout_10",
        "population": "B0",
        "explore_t": 2.1,
        "explore_estimate_bps": 3.0,
    }
    (out / "choices.json").write_text(json.dumps({f: choice for f in e2.FAMILIES}))
    (out / "exploration.json").write_text(
        json.dumps({"variants": [{"estimate": 0.001}, {"estimate": -1}]})
    )
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text("# Decisions\n")
    assert e2.record_choices(out, decisions) and not e2.record_choices(out, decisions)
    row = choice | {
        "estimate_bps": 2.0,
        "interval_95_bps": [-1.0, 5.0],
        "p_one_sided": 0.1,
        "p_holm": 0.3,
        "years_positive": 4,
        "passes": False,
    }
    (out / "confirmation.json").write_text(
        json.dumps({"families": {f: row for f in e2.FAMILIES}, "choices_sha256": "a" * 64})
    )
    assert e2.record_results(out, decisions) and not e2.record_results(out, decisions)
    text = decisions.read_text()
    assert "### 59a. " in text and "## 60. " in text and "none is adopted" in text
    assert text.count("E5_timeout_10") == 6

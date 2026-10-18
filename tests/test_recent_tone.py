import hashlib

import numpy as np
import pandas as pd

from structural_break.intelligence import recent_tone as rt


class FakeFinBERT:
    model_name = rt.TONE_POLICY.model_name
    model_revision = rt.TONE_POLICY.model_revision

    def token_ids(self, text: str) -> list[int]:
        return [len(word) for word in text.split()]

    def predict(self, windows: list[list[int]]) -> list[dict[str, float]]:
        return [{"positive": 0.7, "negative": 0.1, "neutral": 0.2} for _ in windows]


def _pack(text: str) -> dict:
    return {
        "chunks": [{"chunk_text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}]
    }


def test_score_pack_weights_windows_by_tokens() -> None:
    text = "The company reported record quarterly revenue growth of twelve percent this year."
    record = rt.score_pack(_pack(text), FakeFinBERT())
    assert record["status"] == "OK" and record["tokens"] > 0
    assert abs(record["positive"] - 0.7) < 1e-9 and abs(record["negative"] - 0.1) < 1e-9
    assert rt.score_pack({"chunks": []}, FakeFinBERT())["status"] == "NO_SCORABLE_TEXT"


def test_tone_features_code_no_news_as_zero_and_unknown_as_null() -> None:
    events = pd.DataFrame(
        [{"event_id": "e1", "abnormal_return_A_1d": -0.04, "abnormal_return_B_1d": 0.01}]
    )
    windows = pd.DataFrame(
        [
            {"event_id": "e1", "leg": "a", "known": True, "filing_ids": ["f1"], "leg_key": "k"},
            {"event_id": "e1", "leg": "b", "known": True, "filing_ids": [], "leg_key": None},
        ]
    )
    tone = {"status": "OK", "positive": 0.1, "negative": 0.8, "neutral": 0.1}
    row = rt.tone_features(events, windows, lambda key: tone).iloc[0]
    assert np.isclose(row["news_tone_a_net"], -0.7) and row["news_tone_b_net"] == 0
    assert np.isclose(row["news_tone_contrast"], -0.7)
    assert np.isclose(row["news_tone_mover_aligned"], 0.7)  # negative tone, stock fell
    unknown = windows.assign(known=[False, True])
    row = rt.tone_features(events, unknown, lambda key: tone).iloc[0]
    assert np.isnan(row["news_tone_a_net"]) and np.isnan(row["news_tone_mover_net"])

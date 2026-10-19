import numpy as np
import pandas as pd

from structural_break.experiments import p6_sec_explore3 as e3


def test_combination_gain_is_measured_over_the_news_exit() -> None:
    n = 120
    flagged = np.arange(n) % 3 == 0
    data = pd.DataFrame(
        {
            "event_date": pd.date_range("2008-01-01", periods=n, freq="MS").date,
            "frozen_net": np.where(flagged, -0.03, 0.001),
            f"{e3.EXIT}|net": np.where(flagged, -0.02, 0.002),
            "mover_tone_negative": np.where(flagged, 0.5, np.nan),
        }
    )
    result = e3.combination_contrast(data, "C1_S5_negative_recent_tone", (2006, 2025))
    assert np.isclose(result["estimate_bps"], 200 / 3)  # skipping -2 % trades on a third of events
    assert result["versus_frozen"]["estimate_bps"] > result["estimate_bps"]
    assert np.isclose(result["reduced_share"], 1 / 3)


def test_every_combination_returns_weights_in_unit_interval() -> None:
    frame = pd.DataFrame(
        {
            "mover_tone_negative": [0.0, 0.3, np.nan],
            "h_neg_1s": [0.5, np.nan, 0.0],
            "h_net_1s": [-0.5, np.nan, 0.2],
            "h_neg_3s": [0.1, 0.9, np.nan],
            "h_count_5s": [3, 0, 1],
            "mover_earnings_3s": [1.0, 0.0, np.nan],
            "news_mover_explains_move": [0.0, 1.0, np.nan],
            "mover_news_earnings": [0.0, 1.0, 0.0],
            "mover_news_corporate": [1.0, 0.0, 0.0],
            "mover_news_material": [1.0, 0.0, 0.0],
        }
    )
    for weight in e3.ENTRY_WEIGHTS.values():
        values = weight(frame)
        assert values.between(0, 1).all() and len(values) == 3

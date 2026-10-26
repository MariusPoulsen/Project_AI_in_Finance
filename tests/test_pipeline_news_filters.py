import numpy as np
import pandas as pd

from structural_break.pipeline import news_filters as ex


def _frame(n: int = 240) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    news = (np.arange(n) % 4 == 0).astype(float)
    return ex.add_mover_columns(
        pd.DataFrame(
            {
                "event_date": pd.date_range("2008-01-01", periods=n, freq="7D").date,
                "abnormal_return_A_1d": np.where(news > 0, -0.05, 0.01),
                "abnormal_return_B_1d": 0.005,
                "sec_a_8k_1s": news,
                "sec_b_8k_1s": 0.0,
                "sec_a_earnings_3s": 0.0,
                "sec_b_earnings_3s": 0.0,
                **{
                    f"news_{leg}_{f}": 0.0
                    for leg in "ab"
                    for f in ("material", "negative", "positive", "earnings", "corporate")
                },
                "news_tone_a_negative": 0.0,
                "news_tone_b_negative": 0.0,
                "frozen|status": "COMPLETE",
                "frozen|net": np.where(news > 0, -0.02, 0.001) + rng.normal(0, 1e-4, n),
                "baseline1_eligible": True,
                "y_revert_success": 1 - news,
            }
        )
    )


def test_mover_columns_follow_the_larger_abnormal_return() -> None:
    frame = _frame()
    assert frame.loc[0, "mover_fell"] and frame.loc[0, "mover_8k_1s"] == 1
    assert not frame.loc[1, "mover_fell"] and frame.loc[1, "mover_8k_1s"] == 0


def test_bootstrap_reports_interval_se_and_one_sided_p() -> None:
    months = np.array(["2010-01", "2010-02", "2010-03", "2010-04"] * 10)
    stats = ex.bootstrap(np.full(40, 0.001), months)
    assert stats["estimate_bps"] == 10.0 and stats["p_one_sided"] == 0.0


from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from structural_break.forecast import model_b_scores as b2


def _frame(n: int = 1200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    signal = rng.normal(size=n)
    frame = pd.DataFrame(
        {
            "f1": signal,
            "f2": rng.normal(size=n),
            b2.TARGET: (rng.random(n) < 1 / (1 + np.exp(-(2 * signal - 1)))).astype(float),
            "frozen|status": np.where(rng.random(n) < 0.9, "COMPLETE", "NO_FILL"),
            "frozen|net": rng.normal(0, 0.01, n),
        }
    )
    return frame


def test_r0_scores_rank_the_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(b2.pb.FIXED_XGB, "n_estimators", 20)
    frame = _frame()
    probabilities = b2.score(frame.iloc[:1000], frame.iloc[1000:], ("f1", "f2"))
    assert probabilities.shape == (200,)
    assert ((probabilities > 0) & (probabilities < 1)).all()
    labels = frame[b2.TARGET].iloc[1000:].to_numpy()
    assert probabilities[labels == 1].mean() > probabilities[labels == 0].mean()


def test_sharpe_of_monthly_means() -> None:
    allocations = pd.Series([0.01, 0.03, 0.0, 0.02])
    months = pd.Series(["2010-01", "2010-01", "2010-02", "2010-02"])
    assert b2.sharpe(allocations, months) == pytest.approx(
        0.015 / np.std([0.02, 0.01], ddof=1) * np.sqrt(12)
    )

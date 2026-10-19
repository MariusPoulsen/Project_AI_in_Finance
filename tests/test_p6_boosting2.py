from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from structural_break.experiments import p6_boosting2 as b2
from structural_break.experiments.p6_coint import FEATURES


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
    for name in FEATURES:
        frame[name] = rng.normal(size=n)
    return frame


def test_return_weights_are_clipped_and_normalised() -> None:
    frame = _frame()
    frame.loc[0, "frozen|net"] = 5.0
    weights = b2.return_weights(frame)
    assert weights.mean() == pytest.approx(1.0)
    assert weights.max() < 10
    assert (weights > 0).all()


@pytest.mark.parametrize("name", [b2.BASE, *b2.VARIANTS])
def test_every_variant_scores(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(b2, "SEEDS", (0, 1))
    monkeypatch.setitem(b2.pb.FIXED_XGB, "n_estimators", 20)
    frame = _frame()
    options = b2.VARIANTS.get(name, {})
    probabilities = b2.score(options, frame.iloc[:1000], frame.iloc[1000:], ("f1", "f2"))
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

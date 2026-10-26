import math

import numpy as np
import pandas as pd

from structural_break.book import residual_sleeve as pr


def _panels(days: int = 6) -> pr.Panels:
    dates = pd.bdate_range("2020-01-01", periods=days)
    returns = np.zeros((days, 2))
    open_returns = np.full((days, 2), 0.01)
    return pr.Panels(
        dates=dates,
        tickers=["A", "B"],
        returns=returns,
        open_returns=open_returns,
        etf={"SPY": np.zeros(days)},
        vol20=np.full((days, 2), 0.02),
        adv20=np.full((days, 2), 1e8),
        sectors=["X", "X"],
    )


def test_ou_scores_recovers_persistence_and_sign() -> None:
    rng = np.random.default_rng(0)
    b, n = 0.8, 4000
    x = np.zeros((n, 2))
    for t in range(1, n):
        x[t] = b * x[t - 1] + rng.standard_normal(2) * 0.01
    x[-1] = [0.05, -0.05]  # stock 0 far above equilibrium, stock 1 far below
    residuals = np.diff(np.vstack([np.zeros((1, 2)), x]), axis=0)
    s, kappa = pr.ou_scores(residuals)
    assert np.allclose(kappa, -math.log(b) * 252, rtol=0.15)
    # About three equilibrium deviations above and below.
    assert s[0] > 2 and s[1] < -2


def test_neutralise_removes_sector_and_beta_exposure() -> None:
    rng = np.random.default_rng(1)
    raw = rng.standard_normal(12)
    sectors = ["a"] * 6 + ["b"] * 6
    beta = rng.uniform(0.5, 1.5, 12)
    w = pr.neutralise(raw, sectors, beta)
    assert abs(w[:6].sum()) < 1e-12 and abs(w[6:].sum()) < 1e-12
    assert abs(w @ beta) < 1e-12


def test_run_book_nets_offsetting_trades() -> None:
    panels = _panels()
    d = panels.dates
    # The pairs sleeve buys 10 % of A at day 1 and sells it at day 3; the
    # residual sleeve wants +10 % of A from day 3 (decided at day 2's close).
    legs = [pr.Leg("A", d[1], d[3], 0.10)]
    targets = np.zeros((len(d), 2))
    targets[2:, 0] = 0.10
    netted = pr.run_book(panels, targets, legs, d[0], d[-1], capital=1e6)
    separate = pr.run_book(panels, targets, legs, d[0], d[-1], capital=1e6, net=False)
    assert netted["cost"].sum() < separate["cost"].sum()
    # Day 0: nothing held, NAV unchanged; day 1: 10 % long earns 1 % less entry costs.
    assert netted["nav"].iloc[0] == 1.0
    day1 = netted.iloc[1]
    assert math.isclose(day1["nav"], 1.0 + 0.10 * 0.01 - day1["cost"], rel_tol=1e-12)


def test_close_timing_earns_next_close_to_close_return() -> None:
    panels = _panels()
    panels.returns[:] = 0.02
    d = panels.dates
    book = pr.run_book(panels, None, [pr.Leg("A", d[1], d[3], 0.10)], d[0], d[-1], capital=1e6, timing="close")
    day1 = book.iloc[1]
    assert math.isclose(day1["nav"], 1.0 + 0.10 * 0.02 - day1["cost"], rel_tol=1e-12)
    assert book.iloc[3]["names"] == 0


def test_vol_target_scales_new_entries_within_clip() -> None:
    panels = _panels(days=40)
    d = panels.dates
    legs = [pr.Leg("A", d[1], d[2], 0.10), pr.Leg("A", d[30], d[31], 0.10)]
    book = pr.run_book(panels, None, legs, d[0], d[-1], capital=1e6, vol_target=0.10)
    # Returns are almost constant, so realised volatility is tiny and the scale hits its cap.
    assert book.iloc[1]["scale"] == 1.0 and book.iloc[30]["scale"] == 2.0
    assert math.isclose(book.iloc[30]["gross"], 0.20, rel_tol=0.01)


def test_gross_cap_shrinks_new_entries_but_keeps_open_legs() -> None:
    panels = _panels(days=8)
    d = panels.dates
    legs = [pr.Leg("A", d[1], d[6], 1.5), pr.Leg("B", d[2], d[6], -1.0)]
    book = pr.run_book(panels, None, legs, d[0], d[-1], capital=1e6, max_gross=2.0)
    # Day 2 already holds about 1.5 of NAV in A, so B only gets about half its size.
    assert book.iloc[1]["room"] == 1.0
    assert 0.45 < book.iloc[2]["room"] < 0.55
    assert math.isclose(book.iloc[2]["gross"], 2.0, rel_tol=1e-9)

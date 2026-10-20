from __future__ import annotations

import pytest

from structural_break.backtest.portfolio import simulate_portfolio
from structural_break.backtest.portfolio_fixtures import fixture_portfolio
from structural_break.backtest.simulator import simulate_pair_trade
from structural_break.experiments import p6_portfolio as pp


def _inputs():  # type: ignore[no-untyped-def]
    proposals, policy, config = fixture_portfolio()
    results = {p.request.event_id: simulate_pair_trade(p.request, config) for p in proposals}
    return proposals, policy, config, results


def test_research_copy_reproduces_frozen_portfolio() -> None:
    proposals, policy, config, results = _inputs()
    frozen = simulate_portfolio(proposals, policy, config)
    copy = pp.research_portfolio(
        proposals, results, {}, policy, config, policy.target_entry_fraction
    )
    frozen_close = [m.nav for m in frozen.marks if m.phase == "CLOSE"]
    assert copy["marks"]["nav"].tolist() == pytest.approx(frozen_close, abs=1e-12)
    statuses = {t.event_id: t.status for t in frozen.trades}
    for event_id, status in copy["status"].items():
        if status == "COMPLETE":
            assert statuses[event_id] == "COMPLETE"


def test_weights_scale_entries() -> None:
    proposals, policy, config, results = _inputs()
    base = pp.research_portfolio(proposals, results, {}, policy, config, 0.05)
    heavy = {p.request.event_id: 2.0 for p in proposals}
    doubled = pp.research_portfolio(proposals, results, heavy, policy, config, 0.05)
    first = base["marks"]["nav"].dropna()
    second = doubled["marks"]["nav"].dropna()
    base_change = first.iloc[-1] - 1.0
    doubled_change = second.iloc[-1] - 1.0
    assert doubled_change == pytest.approx(2 * base_change, rel=0.2)


def test_metrics_from_marks() -> None:
    import pandas as pd

    marks = pd.DataFrame(
        {
            "session_date": pd.bdate_range("2016-01-04", periods=4).date,
            "nav": [1.01, 1.0201, 1.0099, 1.02],
            "daily_return": [0.01, 0.01, -0.01, 0.01],
            "drawdown": [0, 0, -0.01, 0],
            "gross_fraction": [0.5] * 4,
            "open_positions": [1] * 4,
        }
    )
    result = pp.metrics(marks)
    assert result["full"]["total_return"] == pytest.approx(1.01**3 * 0.99 - 1)
    assert result["full"]["max_drawdown"] == pytest.approx(-0.01)

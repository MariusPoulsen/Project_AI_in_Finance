
import pytest

from structural_break.backtest.simulator import simulate_pair_trade
from structural_break.book import long_exit as hl
from tests.test_pair_simulator import path, policy

PATHS = [
    [1.8, 1.2, 0.4, 0.2, 0.1, 0.3, 0.2, 0.1, 0.2, 0.3],  # converges
    [2.2, 2.6, 3.1, 2.0, 1.0, 0.5, 0.2, 0.1, 0.1, 0.2],  # adverse stop
    [2.0, 1.9, 1.8, 1.7, 1.6, 1.5, 1.4, 1.3, 1.2, 1.1],  # times out
]


@pytest.mark.parametrize("zs", PATHS)
def test_research_copy_matches_the_frozen_simulator(zs: list[float]) -> None:
    config = policy(horizon_sessions=10)
    request = path(zs)
    frozen = simulate_pair_trade(request, config)
    copy = hl.simulate_long(request, request.sessions, request.prices, config, 10)
    assert copy["status"] == frozen.status and copy["reason"] == frozen.reason
    assert copy["holding"] == frozen.holding_sessions
    assert copy["net"] == pytest.approx(frozen.net_return, abs=1e-15)


def test_a_longer_timeout_keeps_holding_until_convergence() -> None:
    zs = [2.0, 1.9, 1.8, 1.7, 1.6, 1.5, 1.4, 1.3, 1.2, 1.1, 0.4, 0.3]
    config = policy(horizon_sessions=10)
    request = path(zs)
    short = hl.simulate_long(request, request.sessions, request.prices, config, 5)
    longer = hl.simulate_long(request, request.sessions, request.prices, config, 12)
    assert short["reason"] == "TIMEOUT" and short["holding"] == 5
    assert longer["reason"] == "CONVERGENCE" and longer["holding"] == 11


def test_news_after_the_signal_exits_at_the_next_open() -> None:
    zs = [2.0, 1.9, 1.8, 1.7, 1.6, 1.5, 1.4, 1.3, 1.2, 1.1]
    config = policy(horizon_sessions=10)
    request = path(zs)
    third_close = request.sessions[3].close_at
    news = hl.simulate_long(request, request.sessions, request.prices, config, 10, [third_close])
    assert news["reason"] == "NEWS_EXIT" and news["holding"] == 3
    before = hl.simulate_long(
        request, request.sessions, request.prices, config, 10, [request.signal_at]
    )
    assert before["reason"] == "TIMEOUT"  # news already known at the signal is not an exit

"""Two simultaneous positions with independently calculable unit-ledger NAV."""

from structural_break.backtest.contracts import ExecutionConfig, PairPrices, PairTradeRequest
from structural_break.backtest.fixtures import synthetic_trade_request
from structural_break.backtest.portfolio import PortfolioPolicy, PortfolioProposal
from structural_break.backtest.simulator import fixture_config


def fixture_portfolio() -> tuple[tuple[PortfolioProposal, ...], PortfolioPolicy, ExecutionConfig]:
    source = synthetic_trade_request()
    bars = list(source.prices)
    # Every held open/close is explicit; exit close is irrelevant after disposal.
    bars[0] = bars[0].model_copy(update={"open_a": 200.0, "open_b": 100.0})
    bars[2] = bars[2].model_copy(update={"close_a": 189.0, "close_b": 110.0})
    first = PairTradeRequest.model_validate(
        {**source.model_dump(), "prices": tuple(bars)}, strict=True
    )
    second = PairTradeRequest.model_validate(
        {
            **first.model_dump(),
            "event_id": "synthetic-second-portfolio-event-v1",
            "pair_id": "CCC__DDD",
            "leg_a": "CCC",
            "leg_b": "DDD",
            "prices": tuple(PairPrices.model_validate(bar.model_dump()) for bar in bars),
        },
        strict=True,
    )
    proposals = tuple(
        PortfolioProposal(
            request=event,
            decision_id="fixture-portfolio-selection-v1",
            decision_at=event.signal_at,
            sector_a="TECHNOLOGY",
            sector_b="TECHNOLOGY",
        )
        for event in (first, second)
    )
    return proposals, PortfolioPolicy(version="fixture-portfolio-policy-v1"), fixture_config()

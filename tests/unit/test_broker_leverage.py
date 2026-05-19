"""Phase F4.5 — BacktestBroker / StrategyAPI leverage exposure.

cfg.run.leverage is forwarded broker.__init__(leverage=...) and then
exposed via api.leverage so strategies (future_demo) can multiply the
sequence-derived notional by leverage to compute qty.

Note: broker accounting is unchanged — leverage is a strategy-side qty
multiplier, not a margin trading semantic. The numeric value is preserved
so the strategy uses it; cash is still debited at notional.
"""

from __future__ import annotations

import pytest

from tickweaver.execution.backtest_broker import BacktestBroker
from tickweaver.execution.fees import NoFee
from tickweaver.execution.slippage import NoSlippage
from tickweaver.strategy.api import StrategyAPI


def _broker(leverage: float = 1.0, mode: str = "futures") -> BacktestBroker:
    return BacktestBroker(
        symbol="T",
        initial_cash=10_000.0,
        fee_model=NoFee(),
        slippage_model=NoSlippage(),
        mode=mode,
        leverage=leverage,
    )


def test_broker_default_leverage_is_one():
    b = BacktestBroker(
        symbol="T",
        initial_cash=10_000.0,
        fee_model=NoFee(),
        slippage_model=NoSlippage(),
    )
    assert b.leverage == 1.0


def test_broker_accepts_leverage_kwarg():
    b = _broker(leverage=100.0)
    assert b.leverage == 100.0


def test_broker_rejects_non_positive_leverage():
    for bad in (0.0, -1.0):
        with pytest.raises(Exception):
            _broker(leverage=bad)


def test_api_leverage_forwards_broker_leverage():
    b = _broker(leverage=25.0)
    api = StrategyAPI(broker=b, symbol="T", console_log=False)
    assert api.leverage == 25.0


def test_api_leverage_default_is_one():
    b = BacktestBroker(
        symbol="T",
        initial_cash=10_000.0,
        fee_model=NoFee(),
        slippage_model=NoSlippage(),
    )
    api = StrategyAPI(broker=b, symbol="T", console_log=False)
    assert api.leverage == 1.0

"""LIMIT / STOP / STOP_LIMIT 단위 테스트.

각 시나리오: broker 인스턴스 + 주문 발주 + tick 시퀀스 → 체결 결과 확인.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tickweaver.core.exceptions import OrderError
from tickweaver.core.types import Order, OrderType, Side, Tick
from tickweaver.execution.backtest_broker import BacktestBroker
from tickweaver.execution.fees import NoFee
from tickweaver.execution.slippage import NoSlippage


def _broker(**kw) -> BacktestBroker:
    return BacktestBroker(
        symbol="TEST",
        initial_cash=10_000.0,
        fee_model=NoFee(),
        slippage_model=NoSlippage(),
        **kw,
    )


def _order(side: Side, type: OrderType, qty: float, price=None, stop_price=None) -> Order:
    return Order(
        order_id=f"O-{type.name}-{side.name}",
        client_order_id="C",
        symbol="TEST",
        side=side,
        type=type,
        qty=qty,
        price=price,
        stop_price=stop_price,
        created_at=pd.Timestamp("2024-01-01", tz="UTC"),
    )


def _tick(price: float, idx: int = 0) -> Tick:
    return Tick(
        timestamp=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(seconds=idx),
        price=price,
        bar_index=0,
        tick_index_in_bar=idx,
    )


# ─────────────────────────────────────────────────────────
# LIMIT BUY
# ─────────────────────────────────────────────────────────
def test_limit_buy_fills_when_tick_dips_to_limit():
    b = _broker()
    b.submit(_order(Side.BUY, OrderType.LIMIT, qty=1.0, price=100.0))

    # 가격이 limit 위에 있으면 체결 안 됨
    b.on_market_event(_tick(101.0, 0))
    assert b.fills() == []
    assert len(b.open_orders()) == 1

    # 가격이 limit 까지 하락 → 체결 (가격 = limit, 슬리피지 X)
    b.on_market_event(_tick(99.5, 1))
    assert len(b.fills()) == 1
    assert b.fills()[0].price == 100.0  # limit price 로 체결
    assert b.position().qty == 1.0
    assert b.position().entry_price == 100.0


def test_limit_buy_does_not_fill_above_limit():
    b = _broker()
    b.submit(_order(Side.BUY, OrderType.LIMIT, qty=1.0, price=100.0))
    for p in (105.0, 103.0, 101.0, 100.5):
        b.on_market_event(_tick(p))
    assert b.fills() == []


# ─────────────────────────────────────────────────────────
# LIMIT SELL
# ─────────────────────────────────────────────────────────
def test_limit_sell_fills_when_tick_rises_to_limit():
    b = _broker()
    b.submit(_order(Side.SELL, OrderType.LIMIT, qty=1.0, price=110.0))

    b.on_market_event(_tick(105.0, 0))
    assert b.fills() == []

    b.on_market_event(_tick(110.5, 1))  # limit 이상 → 체결
    assert len(b.fills()) == 1
    assert b.fills()[0].price == 110.0


# ─────────────────────────────────────────────────────────
# STOP SELL (손절)
# ─────────────────────────────────────────────────────────
def test_stop_sell_triggers_at_stop_loss():
    b = _broker()
    # 먼저 LONG 진입
    b.submit(_order(Side.BUY, OrderType.MARKET, qty=1.0))
    b.on_market_event(_tick(100.0, 0))
    assert b.position().qty == 1.0

    # 손절 STOP SELL 발주
    b.submit(_order(Side.SELL, OrderType.STOP, qty=1.0, stop_price=95.0))
    # 가격이 95 위에 있으면 미체결
    b.on_market_event(_tick(98.0, 1))
    b.on_market_event(_tick(96.0, 2))
    assert len(b.fills()) == 1  # buy 1건만

    # 가격이 95 이하 → STOP 트리거 → 시장가 체결
    b.on_market_event(_tick(94.5, 3))
    assert len(b.fills()) == 2
    assert b.fills()[1].price == 94.5  # 트리거 시점 가격
    assert b.position().is_flat


# ─────────────────────────────────────────────────────────
# STOP BUY (브레이크아웃 진입)
# ─────────────────────────────────────────────────────────
def test_stop_buy_triggers_on_breakout():
    b = _broker()
    b.submit(_order(Side.BUY, OrderType.STOP, qty=1.0, stop_price=110.0))

    b.on_market_event(_tick(105.0, 0))
    b.on_market_event(_tick(109.0, 1))
    assert b.fills() == []

    b.on_market_event(_tick(110.5, 2))  # 트리거
    assert len(b.fills()) == 1
    assert b.fills()[0].price == 110.5
    assert b.position().qty == 1.0


# ─────────────────────────────────────────────────────────
# STOP_LIMIT
# ─────────────────────────────────────────────────────────
def test_stop_limit_buy_triggers_then_waits_for_limit():
    b = _broker()
    # stop=110, limit=109 (트리거 후 109 이하로 다시 내려와야 체결)
    b.submit(
        _order(Side.BUY, OrderType.STOP_LIMIT, qty=1.0, price=109.0, stop_price=110.0)
    )

    # 트리거 안 됨
    b.on_market_event(_tick(105.0, 0))
    assert b.fills() == []

    # 트리거 (110 도달) — 그러나 같은 tick 가격이 limit 109 보다 높으니 미체결
    b.on_market_event(_tick(110.5, 1))
    assert b.fills() == []
    assert len(b.open_orders()) == 1  # 여전히 대기 중

    # 가격이 109 까지 하락 → LIMIT 체결
    b.on_market_event(_tick(108.5, 2))
    assert len(b.fills()) == 1
    assert b.fills()[0].price == 109.0


# ─────────────────────────────────────────────────────────
# 주문 검증
# ─────────────────────────────────────────────────────────
def test_limit_requires_price():
    b = _broker()
    bad = Order(
        order_id="X",
        client_order_id="X",
        symbol="TEST",
        side=Side.BUY,
        type=OrderType.LIMIT,
        qty=1.0,
        price=None,
        stop_price=None,
        created_at=pd.Timestamp("2024-01-01", tz="UTC"),
    )
    with pytest.raises(OrderError):
        b.submit(bad)


def test_stop_requires_stop_price():
    b = _broker()
    bad = Order(
        order_id="X",
        client_order_id="X",
        symbol="TEST",
        side=Side.SELL,
        type=OrderType.STOP,
        qty=1.0,
        price=None,
        stop_price=None,
        created_at=pd.Timestamp("2024-01-01", tz="UTC"),
    )
    with pytest.raises(OrderError):
        b.submit(bad)


def test_cancel_open_order():
    b = _broker()
    o = _order(Side.BUY, OrderType.LIMIT, qty=1.0, price=100.0)
    b.submit(o)
    assert len(b.open_orders()) == 1
    assert b.cancel(o.order_id) is True
    assert b.open_orders() == []
    # 이후 가격이 limit 까지 와도 체결 안 됨
    b.on_market_event(_tick(99.0))
    assert b.fills() == []

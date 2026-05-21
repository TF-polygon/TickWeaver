"""Issue 1 — BacktestBroker 의 qty_step 기반 dust epsilon 검증.

마틴게일 N add cycle 의 close 후 broker net 에 1 step 정도의 부동소수점
잔여가 남는 케이스를 broker 가 자동 FLAT 처리하는지 확인. 이전엔
strategy 측에서 `api.is_flat() or qty < epsilon` 같은 가드로 우회했지만
이제는 broker 가 직접 정리.
"""

from __future__ import annotations

import itertools

import pandas as pd
import pytest

from tickweaver.core.exceptions import OrderError
from tickweaver.core.types import Order, OrderType, PositionSide, Side, Tick
from tickweaver.execution.backtest_broker import BacktestBroker
from tickweaver.execution.fees import NoFee
from tickweaver.execution.slippage import NoSlippage


_coid = itertools.count(1)


def _broker(qty_step: float = 1e-6, mode: str = "futures") -> BacktestBroker:
    return BacktestBroker(
        symbol="T",
        initial_cash=10_000.0,
        fee_model=NoFee(),
        slippage_model=NoSlippage(),
        mode=mode,
        leverage=1.0,
        qty_step=qty_step,
    )


def _order(side: Side, qty: float) -> Order:
    n = next(_coid)
    return Order(
        order_id=f"ORD-{n}",
        client_order_id=f"COID-{n}",
        symbol="T",
        side=side,
        type=OrderType.MARKET,
        qty=qty,
        price=None,
        stop_price=None,
        created_at=pd.Timestamp("2024-01-01", tz="UTC"),
    )


def _tick(price: float, idx: int = 0) -> Tick:
    return Tick(
        timestamp=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(seconds=idx),
        price=price,
        bar_index=0,
        tick_index_in_bar=idx,
    )


def _market_fill(broker: BacktestBroker, side: Side, qty: float, price: float):
    """Market 발주 + 즉시 fill."""
    broker.submit(_order(side, qty))
    broker.on_market_event(_tick(price))


# ──────────────────────────────────────────────────────────
# qty_step argument 검증
# ──────────────────────────────────────────────────────────


def test_default_qty_step_is_1e_minus_6():
    b = BacktestBroker(symbol="X", fee_model=NoFee(), slippage_model=NoSlippage())
    assert b._qty_step == 1e-6
    assert b._qty_dust_eps == pytest.approx(1.5e-6)


def test_custom_qty_step():
    b = _broker(qty_step=0.001)
    assert b._qty_step == 0.001
    assert b._qty_dust_eps == pytest.approx(0.0015)


def test_qty_step_must_be_positive():
    with pytest.raises(OrderError):
        _broker(qty_step=0)
    with pytest.raises(OrderError):
        _broker(qty_step=-1e-6)


# ──────────────────────────────────────────────────────────
# 핵심 케이스 — 마틴게일 N add close 후 dust 잔여 자동 청소
# ──────────────────────────────────────────────────────────


def test_simple_long_close_lands_at_flat():
    """Buy 1 → Sell 1 → FLAT. 회귀 보장."""
    b = _broker()
    _market_fill(b, Side.BUY, 1.0, 100.0)
    assert b.position().side == PositionSide.LONG
    _market_fill(b, Side.SELL, 1.0, 110.0)
    assert b.position().side == PositionSide.FLAT


def test_martingale_two_add_close_lands_at_flat_with_floating_point_residue():
    """마틴게일 2 add 후 한 fill 로 close → broker net 부동소수점 잔여 자동 청소.

    실제 케이스 재현: 0.066709 + 0.133421 = 0.20012899999...
    close 발주 qty 가 round_qty floor 로 0.200129 가 되면 잔여 ≈ 1e-6.
    dust epsilon (= 1.5e-6) 이 그것을 잡아 FLAT 처리.
    """
    b = _broker(qty_step=1e-6)
    _market_fill(b, Side.SELL, 0.066709, 44970.0)
    _market_fill(b, Side.SELL, 0.133421, 45085.0)
    assert b.position().side == PositionSide.SHORT
    # close qty 가 broker net 보다 1 step 작아도 (floor 결과)
    _market_fill(b, Side.BUY, 0.200129, 45135.0)
    # 잔여 ≈ 1e-6 < dust_eps (= 1.5e-6) → FLAT
    assert b.position().side == PositionSide.FLAT, (
        f"broker net 에 dust 잔여가 정리되지 않음. "
        f"qty={b.position().qty}, dust_eps={b._qty_dust_eps}"
    )


def test_dust_one_step_residue_treated_as_flat():
    """정확히 1 step 잔여 — FLAT 처리 (1e-6 < 1.5e-6)."""
    b = _broker(qty_step=1e-6)
    _market_fill(b, Side.BUY, 1.0, 100.0)
    _market_fill(b, Side.SELL, 0.999999, 110.0)
    assert b.position().side == PositionSide.FLAT


def test_actual_position_qty_above_dust_eps_stays_open():
    """0.001 trading qty (1000 step) 잔여 → 정상 open 상태 유지."""
    b = _broker(qty_step=1e-6)
    _market_fill(b, Side.BUY, 1.0, 100.0)
    _market_fill(b, Side.SELL, 0.999, 110.0)
    pos = b.position()
    assert pos.side == PositionSide.LONG
    assert pos.qty == pytest.approx(0.001)


# ──────────────────────────────────────────────────────────
# Reverse fill — close + 새 진입 한 fill 후 net qty 검증
# ──────────────────────────────────────────────────────────


def test_reverse_fill_closes_and_opens_with_dust_safe():
    """Long 1 → Sell 3 → close 1 + open short 2. broker net = short 2."""
    b = _broker(qty_step=1e-6)
    _market_fill(b, Side.BUY, 1.0, 100.0)
    _market_fill(b, Side.SELL, 3.0, 95.0)
    pos = b.position()
    assert pos.side == PositionSide.SHORT
    assert pos.qty == pytest.approx(2.0)


# ──────────────────────────────────────────────────────────
# Spot mode 영향 없음 검증 (회귀)
# ──────────────────────────────────────────────────────────


def test_spot_mode_dust_handling_intact():
    """spot mode 도 동일 dust 청소 동작."""
    b = _broker(qty_step=1e-6, mode="spot")
    _market_fill(b, Side.BUY, 1.0, 100.0)
    _market_fill(b, Side.SELL, 0.999999, 110.0)
    assert b.position().side == PositionSide.FLAT

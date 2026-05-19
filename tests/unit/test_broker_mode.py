"""Phase F1 (dev/future_mode) — Broker mode-aware validation.

Spot mode must reject SELL orders that would open a short position
(submitted while position is FLAT). Other cases (LONG -> SELL = close)
must still succeed. Futures mode imposes no extra constraint.
"""

from __future__ import annotations

import itertools

import pandas as pd
import pytest

from tickweaver.core.exceptions import OrderError, SpotShortNotAllowedError
from tickweaver.core.types import Order, OrderType, PositionSide, Side, Tick
from tickweaver.execution.backtest_broker import BacktestBroker
from tickweaver.execution.fees import NoFee
from tickweaver.execution.slippage import NoSlippage


_coid = itertools.count(1)


def _broker(mode: str = "futures") -> BacktestBroker:
    return BacktestBroker(
        symbol="T",
        initial_cash=10_000.0,
        fee_model=NoFee(),
        slippage_model=NoSlippage(),
        mode=mode,
    )


def _order(side: Side, otype: OrderType = OrderType.MARKET,
           qty: float = 1.0, price: float | None = None,
           stop_price: float | None = None) -> Order:
    n = next(_coid)
    return Order(
        order_id=f"ORD-{n}",
        client_order_id=f"COID-{n}",
        symbol="T",
        side=side,
        type=otype,
        qty=qty,
        price=price,
        stop_price=stop_price,
        created_at=pd.Timestamp("2024-01-01", tz="UTC"),
    )


def _tick(price: float = 100.0) -> Tick:
    return Tick(
        timestamp=pd.Timestamp("2024-01-01", tz="UTC"),
        price=price,
        bar_index=0,
        tick_index_in_bar=0,
    )


# ─────────────────────────────────────────────────────────
# Spot mode: short-open guard
# ─────────────────────────────────────────────────────────
def test_spot_market_sell_from_flat_raises():
    b = _broker(mode="spot")
    assert b.position().side == PositionSide.FLAT
    with pytest.raises(SpotShortNotAllowedError):
        b.submit(_order(Side.SELL, OrderType.MARKET))


def test_spot_limit_sell_from_flat_raises():
    b = _broker(mode="spot")
    with pytest.raises(SpotShortNotAllowedError):
        b.submit(_order(Side.SELL, OrderType.LIMIT, price=200.0))


def test_spot_stop_sell_from_flat_raises():
    b = _broker(mode="spot")
    with pytest.raises(SpotShortNotAllowedError):
        b.submit(_order(Side.SELL, OrderType.STOP, stop_price=80.0))


def test_spot_stop_limit_sell_from_flat_raises():
    b = _broker(mode="spot")
    with pytest.raises(SpotShortNotAllowedError):
        b.submit(_order(Side.SELL, OrderType.STOP_LIMIT,
                        stop_price=80.0, price=79.0))


def test_spot_market_sell_while_long_succeeds():
    """LONG -> SELL is close, not short open. Must succeed."""
    b = _broker(mode="spot")
    b.submit(_order(Side.BUY, OrderType.MARKET))
    b.on_market_event(_tick(100.0))           # fill BUY -> LONG
    assert b.position().side == PositionSide.LONG
    b.submit(_order(Side.SELL, OrderType.MARKET))  # close: ok in spot


def test_spot_buy_from_flat_succeeds():
    """BUY in spot is always fine (open long)."""
    b = _broker(mode="spot")
    b.submit(_order(Side.BUY, OrderType.MARKET))


# ─────────────────────────────────────────────────────────
# Futures mode: short open is allowed
# ─────────────────────────────────────────────────────────
def test_futures_market_sell_from_flat_succeeds():
    b = _broker(mode="futures")
    b.submit(_order(Side.SELL, OrderType.MARKET))  # opens short -> ok


def test_futures_limit_sell_from_flat_succeeds():
    b = _broker(mode="futures")
    b.submit(_order(Side.SELL, OrderType.LIMIT, price=200.0))


def test_futures_short_then_close_succeeds():
    """SHORT -> BUY is close in futures. Must succeed."""
    b = _broker(mode="futures")
    b.submit(_order(Side.SELL, OrderType.MARKET))
    b.on_market_event(_tick(100.0))           # fill -> SHORT
    assert b.position().side == PositionSide.SHORT
    b.submit(_order(Side.BUY, OrderType.MARKET))  # close short


# ─────────────────────────────────────────────────────────
# Default mode = futures (backwards-compat: existing tests omit `mode=`)
# ─────────────────────────────────────────────────────────
def test_default_mode_is_futures():
    """Broker without mode= argument must default to futures so existing
    callers (including test fixtures) keep working without changes."""
    b = BacktestBroker(
        symbol="T",
        initial_cash=10_000.0,
        fee_model=NoFee(),
        slippage_model=NoSlippage(),
    )
    # No raise expected.
    b.submit(_order(Side.SELL, OrderType.MARKET))


# ─────────────────────────────────────────────────────────
# Error type
# ─────────────────────────────────────────────────────────
def test_spot_short_error_is_an_order_error():
    """SpotShortNotAllowedError must be a subclass of OrderError so existing
    `except OrderError:` blocks in user code keep catching it."""
    assert issubclass(SpotShortNotAllowedError, OrderError)


def test_spot_short_error_message_mentions_spot_and_short():
    b = _broker(mode="spot")
    with pytest.raises(SpotShortNotAllowedError) as excinfo:
        b.submit(_order(Side.SELL, OrderType.MARKET))
    msg = str(excinfo.value).lower()
    assert "spot" in msg
    assert "short" in msg


# ─────────────────────────────────────────────────────────
# Phase F4 — long-only sequences must produce identical state
# across spot and futures modes (mode only adds a guard, no
# accounting behaviour changes).
# ─────────────────────────────────────────────────────────
def _run_buy_then_sell(mode: str):
    """Open LONG via market BUY at tick price 100, close via market SELL at 110."""
    b = _broker(mode=mode)
    b.submit(_order(Side.BUY, OrderType.MARKET))
    b.on_market_event(_tick(100.0))
    b.submit(_order(Side.SELL, OrderType.MARKET))
    b.on_market_event(_tick(110.0))
    return b


def test_long_round_trip_identical_in_spot_and_futures():
    """Long-only strategies must produce bit-identical final cash + fills
    regardless of broker mode. Mode only adds a guard, no accounting change."""
    spot = _run_buy_then_sell("spot")
    fut = _run_buy_then_sell("futures")
    assert spot.cash == fut.cash
    assert spot.equity == fut.equity
    assert spot.position().side == fut.position().side
    assert spot.position().qty == fut.position().qty
    # Fills also identical
    spot_fills = spot._fills
    fut_fills = fut._fills
    assert len(spot_fills) == len(fut_fills)
    for sf, ff in zip(spot_fills, fut_fills):
        assert sf.side == ff.side
        assert sf.price == ff.price
        assert sf.qty == ff.qty


def test_spot_mode_long_only_does_not_raise_on_close():
    """Sanity: a BUY-then-SELL sequence must not trip the short guard."""
    b = _broker(mode="spot")
    b.submit(_order(Side.BUY, OrderType.MARKET))
    b.on_market_event(_tick(100.0))
    # Should NOT raise SpotShortNotAllowedError because position is LONG.
    b.submit(_order(Side.SELL, OrderType.MARKET))
    b.on_market_event(_tick(110.0))
    assert b.position().side == PositionSide.FLAT


def test_futures_short_round_trip_settles_correctly():
    """Open SHORT at 100, close at 90 → +10 per qty of realised PnL."""
    b = _broker(mode="futures")
    initial_cash = b.cash
    b.submit(_order(Side.SELL, OrderType.MARKET, qty=1.0))
    b.on_market_event(_tick(100.0))
    assert b.position().side == PositionSide.SHORT
    b.submit(_order(Side.BUY, OrderType.MARKET, qty=1.0))
    b.on_market_event(_tick(90.0))
    assert b.position().side == PositionSide.FLAT
    # NoFee + NoSlippage → realised PnL = (100 - 90) * 1 = +10
    assert b.cash == initial_cash + 10.0

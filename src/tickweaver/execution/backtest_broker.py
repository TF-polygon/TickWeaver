"""BacktestBroker — MARKET / LIMIT / STOP / STOP_LIMIT.

Lookahead protection (plan.md S.10): submit != fill, only fills inside on_market_event.
Orders submitted in on_bar fill from the FIRST tick of the NEXT bar.

Fill rules:
- MARKET: fills at next tick price + slippage
- LIMIT : fills at limit price (no slippage, maker)
    BUY  : tick.price <= limit_price
    SELL : tick.price >= limit_price
- STOP  : trigger -> market fill at the trigger tick price + slippage
    BUY  : tick.price >= stop_price (breakout / take-profit)
    SELL : tick.price <= stop_price (stop-loss)
- STOP_LIMIT: once triggered, behaves like LIMIT.

Accounting (D2 USDT-M Perpetual):
- entry: cash unchanged (only fee deducted)
- closing: cash += realized PnL
- equity = cash + unrealized_pnl (mark-to-market)
"""

from __future__ import annotations

import itertools
from typing import Callable

import pandas as pd

from tickweaver.core.exceptions import OrderError
from tickweaver.core.types import (
    Fill,
    Order,
    OrderType,
    Position,
    PositionSide,
    Side,
    Tick,
)
from tickweaver.execution.fees import BpsFeeModel, FeeModel, NoFee
from tickweaver.execution.slippage import (
    FixedBpsSlippage,
    NoSlippage,
    SlippageModel,
)


_EPS = 1e-12


class BacktestBroker:
    """Single-asset (D3) backtest broker."""

    def __init__(
        self,
        symbol: str,
        initial_cash: float = 10000.0,
        fee_model: FeeModel | None = None,
        slippage_model: SlippageModel | None = None,
    ) -> None:
        self.symbol = symbol
        self._cash: float = float(initial_cash)
        self._initial_cash: float = float(initial_cash)
        self._position = Position(symbol=symbol)
        self._fee_model: FeeModel = fee_model or BpsFeeModel(5.0)
        self._slippage: SlippageModel = slippage_model or FixedBpsSlippage(2.0)

        self._open_orders: list[Order] = []
        self._triggered: set[str] = set()

        self._fills: list[Fill] = []
        self._fill_callback: Callable[[Fill], None] | None = None
        self._order_id_counter = itertools.count(1)

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def equity(self) -> float:
        return self._cash + self._position.unrealized_pnl

    @property
    def initial_cash(self) -> float:
        return self._initial_cash

    def position(self) -> Position:
        return self._position

    def submit(self, order: Order) -> str:
        if order.qty <= 0:
            raise OrderError(f"order qty must be positive, got {order.qty}")
        if order.symbol != self.symbol:
            raise OrderError(
                f"symbol mismatch: order={order.symbol} vs broker={self.symbol}"
            )

        t = order.type
        if t == OrderType.MARKET:
            pass
        elif t == OrderType.LIMIT:
            if order.price is None or order.price <= 0:
                raise OrderError(f"LIMIT order requires positive price, got {order.price}")
        elif t == OrderType.STOP:
            if order.stop_price is None or order.stop_price <= 0:
                raise OrderError(
                    f"STOP order requires positive stop_price, got {order.stop_price}"
                )
        elif t == OrderType.STOP_LIMIT:
            if order.stop_price is None or order.stop_price <= 0:
                raise OrderError(
                    f"STOP_LIMIT requires positive stop_price, got {order.stop_price}"
                )
            if order.price is None or order.price <= 0:
                raise OrderError(
                    f"STOP_LIMIT requires positive limit price, got {order.price}"
                )
        else:
            raise OrderError(f"unsupported order type: {t}")

        order.status = "open"
        self._open_orders.append(order)
        return order.order_id

    def cancel(self, order_id: str) -> bool:
        before = len(self._open_orders)
        self._open_orders = [o for o in self._open_orders if o.order_id != order_id]
        self._triggered.discard(order_id)
        return len(self._open_orders) < before

    def positions(self) -> dict[str, Position]:
        return {self.symbol: self._position}

    def set_fill_callback(self, cb: Callable[[Fill], None]) -> None:
        self._fill_callback = cb

    def on_market_event(self, tick: Tick) -> list[Fill]:
        if not self._open_orders:
            self._update_mark(tick.price)
            return []

        fills: list[Fill] = []
        still_open: list[Order] = []
        for order in self._open_orders:
            fill = self._try_fill(order, tick)
            if fill is not None:
                fills.append(fill)
            else:
                still_open.append(order)
        self._open_orders = still_open
        self._update_mark(tick.price)
        if self._fill_callback:
            for f in fills:
                self._fill_callback(f)
        return fills

    def _try_fill(self, order: Order, tick: Tick) -> Fill | None:
        t = order.type
        if t == OrderType.MARKET:
            exec_price = self._slippage.adjust(tick.price, order.side)
            return self._execute_at(order, tick, exec_price)
        if t == OrderType.LIMIT:
            return self._try_fill_limit(order, tick)
        if t == OrderType.STOP:
            return self._try_fill_stop_market(order, tick)
        if t == OrderType.STOP_LIMIT:
            return self._try_fill_stop_limit(order, tick)
        return None

    def _try_fill_limit(self, order: Order, tick: Tick) -> Fill | None:
        # LIMIT fills at limit price (maker, no slippage).
        limit = order.price
        if order.side == Side.BUY and tick.price <= limit + _EPS:
            return self._execute_at(order, tick, exec_price=float(limit))
        if order.side == Side.SELL and tick.price >= limit - _EPS:
            return self._execute_at(order, tick, exec_price=float(limit))
        return None

    def _try_fill_stop_market(self, order: Order, tick: Tick) -> Fill | None:
        # STOP triggers -> immediate market fill at trigger tick price + slippage.
        stop = order.stop_price
        triggered = (
            (order.side == Side.BUY and tick.price >= stop - _EPS)
            or (order.side == Side.SELL and tick.price <= stop + _EPS)
        )
        if not triggered:
            return None
        exec_price = self._slippage.adjust(tick.price, order.side)
        return self._execute_at(order, tick, exec_price)

    def _try_fill_stop_limit(self, order: Order, tick: Tick) -> Fill | None:
        # Once triggered, behaves like LIMIT. Same tick may also clear LIMIT.
        if order.order_id not in self._triggered:
            stop = order.stop_price
            triggered = (
                (order.side == Side.BUY and tick.price >= stop - _EPS)
                or (order.side == Side.SELL and tick.price <= stop + _EPS)
            )
            if not triggered:
                return None
            self._triggered.add(order.order_id)
        limit = order.price
        if order.side == Side.BUY and tick.price <= limit + _EPS:
            return self._execute_at(order, tick, exec_price=float(limit))
        if order.side == Side.SELL and tick.price >= limit - _EPS:
            return self._execute_at(order, tick, exec_price=float(limit))
        return None

    def _execute_at(self, order: Order, tick: Tick, exec_price: float) -> Fill:
        fee = self._fee_model.fee(exec_price, order.qty)

        signed_qty = order.qty if order.side == Side.BUY else -order.qty
        old_signed = self._signed_qty()
        old_entry = self._position.entry_price
        new_qty_signed = old_signed + signed_qty
        pnl_realized = 0.0

        if old_signed == 0:
            new_entry = exec_price
        elif (old_signed > 0) == (signed_qty > 0):
            new_entry = (
                (old_entry * abs(old_signed) + exec_price * abs(signed_qty))
                / abs(new_qty_signed)
            )
        else:
            close_qty = min(abs(old_signed), abs(signed_qty))
            if old_signed > 0:
                pnl_realized = (exec_price - old_entry) * close_qty
            else:
                pnl_realized = (old_entry - exec_price) * close_qty

            if abs(signed_qty) <= abs(old_signed) + _EPS:
                new_entry = old_entry if abs(new_qty_signed) > _EPS else 0.0
            else:
                new_entry = exec_price

        self._cash += pnl_realized
        self._cash -= fee

        if abs(new_qty_signed) < _EPS:
            self._position = Position(symbol=self.symbol)
        else:
            side = PositionSide.LONG if new_qty_signed > 0 else PositionSide.SHORT
            self._position = Position(
                symbol=self.symbol,
                side=side,
                qty=abs(new_qty_signed),
                entry_price=new_entry,
                mark_price=exec_price,
                unrealized_pnl=0.0,
            )

        order.status = "filled"
        self._triggered.discard(order.order_id)
        fill = Fill(
            order_id=order.order_id,
            symbol=self.symbol,
            side=order.side,
            qty=order.qty,
            price=exec_price,
            fee=fee,
            timestamp=tick.timestamp,
            pnl_realized=pnl_realized,
        )
        self._fills.append(fill)
        return fill

    def _signed_qty(self) -> float:
        if self._position.side == PositionSide.LONG:
            return self._position.qty
        if self._position.side == PositionSide.SHORT:
            return -self._position.qty
        return 0.0

    def _update_mark(self, price: float) -> None:
        if self._position.side == PositionSide.FLAT:
            return
        signed = self._signed_qty()
        upnl = (price - self._position.entry_price) * signed
        self._position = Position(
            symbol=self.symbol,
            side=self._position.side,
            qty=self._position.qty,
            entry_price=self._position.entry_price,
            mark_price=price,
            unrealized_pnl=upnl,
            liquidation_price=self._position.liquidation_price,
        )

    def fills(self) -> list[Fill]:
        return list(self._fills)

    def open_orders(self) -> list[Order]:
        return list(self._open_orders)

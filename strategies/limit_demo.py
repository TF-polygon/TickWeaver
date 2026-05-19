"""limit_demo.py — LIMIT/STOP 동작 시연.

직전 봉 close 의 -0.3% 에 LIMIT BUY 를 깔고, 진입 후 -1% 손절 STOP SELL +
+1.5% 익절 LIMIT SELL 을 동시에 건다.

레퍼런스: strategies/_reference.md §3
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type stubs for IDE / linter only — never executed at runtime.
    # FileStrategy injects these names into the module namespace right
    # before on_init/on_bar/... are called.
    from tickweaver.core.types import (
        Fill,
        OHLCBar,
        OrderType,
        PositionSide,
        Side,
        StrategyContext,
        Tick,
    )
    from tickweaver.strategy.api import StrategyAPI

    api: StrategyAPI
    context: StrategyContext


prev_close = 0.0
entry_orders_placed = False


def on_init() -> None:
    global prev_close, entry_orders_placed
    prev_close = 0.0
    entry_orders_placed = False


def on_bar(bar: "OHLCBar") -> None:
    global prev_close, entry_orders_placed

    if api.is_flat() and prev_close > 0:
        # 직전 close 보다 -0.3% 저렴한 LIMIT BUY
        limit_price = prev_close * 0.997
        qty = api.size_from_cash_pct(0.3, limit_price)
        if qty > 0:
            api.limit_buy(qty, limit_price)
            entry_orders_placed = True

    if (not api.is_flat()) and entry_orders_placed:
        # 포지션 잡혔으면 손절 + 익절 한 번만 깔고 끝
        pos = api.position()
        if pos.side == PositionSide.LONG:
            stop_loss = pos.entry_price * 0.99
            take_profit = pos.entry_price * 1.015
            api.stop_sell(pos.qty, stop_loss)
            api.limit_sell(pos.qty, take_profit)
            entry_orders_placed = False  # 한 번만

    prev_close = bar.close


def on_fill(fill: "Fill") -> None:
    api.log("fill", side=fill.side.name, price=fill.price, qty=fill.qty,
            pnl_realized=fill.pnl_realized)


def on_deinit() -> None:
    api.log("limit_demo finished",
            final_equity=api.equity,
            position_qty=api.position().qty)

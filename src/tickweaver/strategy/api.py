"""StrategyAPI + ParamsView - gateway injected into file-based strategies.

Reference: strategies/_reference.md sections 3 and 4
"""

from __future__ import annotations

import itertools
import math
from typing import Any

import pandas as pd

from tickweaver.core.types import (
    Order,
    OrderType,
    Position,
    PositionSide,
    Side,
)
from tickweaver.execution.backtest_broker import BacktestBroker
from tickweaver.utils.logger import get_logger


class ParamsView:
    """Read-only view over the paired <strategy>.json (D8)."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(data or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self._data:
            raise KeyError(f"required param missing: {key!r}")
        return self._data[key]

    def contains(self, key: str) -> bool:
        return key in self._data

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __repr__(self) -> str:
        return f"ParamsView({self._data!r})"


class StrategyAPI:
    """Order / position / account gateway. file_strategy injects this as `api`."""

    def __init__(
        self,
        broker: BacktestBroker,
        symbol: str,
        qty_step: float = 1e-6,
        console_log: bool = True,
    ) -> None:
        self._broker = broker
        self._symbol = symbol
        self._qty_step = float(qty_step)
        self._coid_counter = itertools.count(1)
        self._log = get_logger("strategy")
        self._console_log = bool(console_log)

    # ---- orders ----
    def market_buy(self, qty: float) -> str:
        return self._submit(Side.BUY, OrderType.MARKET, qty)

    def market_sell(self, qty: float) -> str:
        return self._submit(Side.SELL, OrderType.MARKET, qty)

    def limit_buy(self, qty: float, price: float) -> str:
        return self._submit(Side.BUY, OrderType.LIMIT, qty, price=float(price))

    def limit_sell(self, qty: float, price: float) -> str:
        return self._submit(Side.SELL, OrderType.LIMIT, qty, price=float(price))

    def stop_buy(self, qty: float, stop_price: float) -> str:
        return self._submit(Side.BUY, OrderType.STOP, qty, stop_price=float(stop_price))

    def stop_sell(self, qty: float, stop_price: float) -> str:
        return self._submit(Side.SELL, OrderType.STOP, qty, stop_price=float(stop_price))

    def stop_limit_buy(self, qty: float, stop_price: float, limit_price: float) -> str:
        return self._submit(
            Side.BUY,
            OrderType.STOP_LIMIT,
            qty,
            price=float(limit_price),
            stop_price=float(stop_price),
        )

    def stop_limit_sell(self, qty: float, stop_price: float, limit_price: float) -> str:
        return self._submit(
            Side.SELL,
            OrderType.STOP_LIMIT,
            qty,
            price=float(limit_price),
            stop_price=float(stop_price),
        )

    # ---- closing ----
    def close_position(self) -> str | None:
        pos = self._broker.position()
        if pos.side == PositionSide.FLAT or pos.qty <= 0:
            return None
        side = Side.SELL if pos.side == PositionSide.LONG else Side.BUY
        return self._submit(side, OrderType.MARKET, pos.qty)

    def close_all(self) -> list[str]:
        oid = self.close_position()
        return [oid] if oid else []

    def cancel(self, order_id: str) -> bool:
        return self._broker.cancel(order_id)

    # ---- queries ----
    def position(self) -> Position:
        return self._broker.position()

    def is_flat(self) -> bool:
        return self._broker.position().side == PositionSide.FLAT

    @property
    def cash(self) -> float:
        return self._broker.cash

    @property
    def equity(self) -> float:
        return self._broker.equity

    # ---- helpers ----
    def round_qty(self, qty: float) -> float:
        if self._qty_step <= 0:
            return float(qty)
        steps = math.floor(qty / self._qty_step)
        return max(steps * self._qty_step, 0.0)

    def size_from_cash_pct(self, pct: float, price: float) -> float:
        if price <= 0:
            return 0.0
        budget = self._broker.cash * float(pct)
        raw = budget / price
        return self.round_qty(raw)

    def log(self, msg: str, **kwargs: Any) -> None:
        # console_log=False -> noop (e.g. when progress bar is on).
        # Use --no-progress on the CLI to see strategy logs in the console.
        if not self._console_log:
            return
        self._log.info(msg, **kwargs)

    # ---- internal ----
    def _submit(
        self,
        side: Side,
        type: OrderType,
        qty: float,
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        qty = self.round_qty(qty)
        if qty <= 0:
            self._log.warning("zero_qty_order", side=side.name, type=type.name)
            return ""
        coid = f"COID-{next(self._coid_counter)}"
        order_id = f"ORD-{coid}"
        order = Order(
            order_id=order_id,
            client_order_id=coid,
            symbol=self._symbol,
            side=side,
            type=type,
            qty=qty,
            price=price,
            stop_price=stop_price,
            created_at=pd.Timestamp.now(tz="UTC"),
        )
        return self._broker.submit(order)

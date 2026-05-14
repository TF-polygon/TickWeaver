"""StrategyAPI - gateway injected into file-based strategies.

Reference: strategies/_reference.md sections 3 and 4
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
from tickweaver.viz.events import (
    IndicatorRegistrationEvent,
    IndicatorSampleEvent,
)

if TYPE_CHECKING:
    from tickweaver.viz.hook import ChartHook


@dataclass
class _IndicatorBinding:
    """Internal record of an api.bind_indicator(...) call.

    - name: full sub-line name, e.g. "EMA fast" (single) or "BB.middle" (sub).
    - indicator: the streaming indicator instance the strategy uses.
    - sub_attr: None for single-value (engine reads .value). For multi-value
                indicators, the attribute name on the indicator to read
                (e.g. 'middle' for BB, 'macd' for MACD).
    """

    name: str
    indicator: Any
    sub_attr: str | None


class StrategyAPI:
    """Order / position / account gateway. file_strategy injects this as `api`."""

    def __init__(
        self,
        broker: BacktestBroker,
        symbol: str,
        qty_step: float = 1e-6,
        console_log: bool = True,
        chart_hook: "ChartHook | None" = None,
    ) -> None:
        self._broker = broker
        self._symbol = symbol
        self._qty_step = float(qty_step)
        self._coid_counter = itertools.count(1)
        self._log = get_logger("strategy")
        self._console_log = bool(console_log)
        self._chart_hook = chart_hook
        # bar context is updated by the engine each bar.
        self._current_bar_index: int = 0
        self._current_bar_timestamp: pd.Timestamp | None = None
        # Phase 3: indicator bindings + names already registered via plot().
        self._indicator_bindings: list[_IndicatorBinding] = []
        self._plot_registered: set[str] = set()

    def _set_bar_index(self, bar_index: int) -> None:
        # Engine-only call to keep comment() bar_index accurate.
        self._current_bar_index = int(bar_index)

    def _set_bar_context(
        self, bar_index: int, timestamp: pd.Timestamp | None
    ) -> None:
        # Engine-only call: keeps both bar_index and timestamp current so
        # api.plot() and api._sample_indicators() can stamp samples correctly.
        self._current_bar_index = int(bar_index)
        self._current_bar_timestamp = timestamp

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
        if not self._console_log:
            return
        self._log.info(msg, **kwargs)

    def comment(self, text: str) -> None:
        """Top-left chart text (MT4 Comment() equivalent, D21).

        Behavior:
            - chart_hook is None: noop (V3, viz disabled)
            - chart_hook is NullHook: noop (default)
            - chart_hook is EventRecorder/LiveChartHook: text replaces the
              top-left label in the live chart window.

        Args:
            text: The text to display. Use ``\n`` for line breaks.
                  Empty string clears the label.
        """
        if self._chart_hook is None:
            return
        self._chart_hook.on_comment(str(text), self._current_bar_index)

    # ---- indicator visualization (Phase 3) ----
    def bind_indicator(
        self,
        name: str,
        indicator: Any,
        panel: str | None = None,
        **style: Any,
    ) -> None:
        """Register an indicator object for automatic per-bar sampling.

        Idempotent: a second call with the same `name` (and an already-bound
        indicator) is a NO-OP, so a stray bind_indicator() inside on_bar
        does not compound per-bar samples. The chart hook still receives an
        updated registration so style/panel changes take effect; sample
        bindings stay deduplicated.

        The engine reads each binding once per bar (after strategy.on_bar)
        and forwards the current value to chart_hook.on_indicator_sample.

        Layout:
            - panel: defaults to indicator.PANEL. Override per-call to remap.
              "price" overlays on the candlestick axis; any other id opens
              a separate sub-panel row.
            - Multi-value indicators (BollingerBands, MACD): SUBVALUES is a
              tuple of attribute names that the engine decomposes into one
              sub-line per entry, named "<name>.<sub>" (e.g. "BB.middle").

        Style kwargs:
            color, width, style (line style) - passed through to the
            live_window renderer. Unknown keys are ignored.

        Noop when chart_hook is None (viz disabled): strategies stay valid
        without changes whether --viz is on or off.
        """
        if self._chart_hook is None:
            return
        resolved_panel = (
            panel if panel is not None else getattr(indicator, "PANEL", "price")
        )
        sub_values = getattr(indicator, "SUBVALUES", None)
        style_dict = dict(style)
        # Pre-compute the target sample names for dedup.
        target_names = (
            [name]
            if sub_values is None
            else [f"{name}.{sub}" for sub in sub_values]
        )
        existing_names = {b.name for b in self._indicator_bindings}
        already_bound = all(n in existing_names for n in target_names)

        if sub_values is None:
            if not already_bound:
                self._indicator_bindings.append(
                    _IndicatorBinding(name=name, indicator=indicator, sub_attr=None)
                )
            # Always forward the registration so the chart hook can apply
            # last-write-wins for panel/style updates.
            self._chart_hook.on_indicator_register(
                IndicatorRegistrationEvent(
                    name=name, panel=resolved_panel, style=style_dict
                )
            )
        else:
            for sub_attr in sub_values:
                full_name = f"{name}.{sub_attr}"
                if not already_bound:
                    self._indicator_bindings.append(
                        _IndicatorBinding(
                            name=full_name, indicator=indicator, sub_attr=sub_attr
                        )
                    )
                self._chart_hook.on_indicator_register(
                    IndicatorRegistrationEvent(
                        name=full_name, panel=resolved_panel, style=style_dict
                    )
                )

    def plot(
        self,
        name: str,
        value: float,
        panel: str = "price",
        **style: Any,
    ) -> None:
        """Low-level fallback: emit a one-shot sample without binding.

        Useful for externally computed values, ad-hoc signals, or non-streaming
        indicators that do not expose PANEL/SUBVALUES. First call for a given
        `name` auto-registers the track (panel + style); subsequent calls only
        emit samples, ignoring further panel/style hints.

        Noop when chart_hook is None.
        """
        if self._chart_hook is None:
            return
        if name not in self._plot_registered:
            self._chart_hook.on_indicator_register(
                IndicatorRegistrationEvent(
                    name=name, panel=panel, style=dict(style)
                )
            )
            self._plot_registered.add(name)
        self._chart_hook.on_indicator_sample(
            IndicatorSampleEvent(
                name=name,
                bar_index=self._current_bar_index,
                timestamp=self._current_bar_timestamp,
                value=float(value),
            )
        )

    def _sample_indicators(
        self, bar_index: int, timestamp: pd.Timestamp | None
    ) -> None:
        """Engine-only: emit one sample per bound indicator line.

        Called after strategy.on_bar(bar) so any update() the strategy did
        inside on_bar is already reflected in indicator.value.

        Warm-up handling: if the value is None (not yet warm) or not a finite
        scalar, the sample is skipped for that line - the viewer will start
        the line at the first warm bar.
        """
        if self._chart_hook is None or not self._indicator_bindings:
            return
        for b in self._indicator_bindings:
            # viz is a read-only observer (V2): a strategy-side .value
            # property that raises must NEVER crash the engine. Skip that
            # binding for this bar and continue.
            try:
                if b.sub_attr is None:
                    raw = getattr(b.indicator, "value", None)
                else:
                    raw = getattr(b.indicator, b.sub_attr, None)
            except Exception as e:
                self._log.warning(
                    "indicator_value_raised",
                    name=b.name,
                    error=type(e).__name__,
                )
                continue
            if raw is None:
                continue
            if not isinstance(raw, (int, float)):
                continue
            # Skip NaN / inf to avoid breaking finplot line segments.
            if isinstance(raw, float) and not math.isfinite(raw):
                continue
            self._chart_hook.on_indicator_sample(
                IndicatorSampleEvent(
                    name=b.name,
                    bar_index=int(bar_index),
                    timestamp=timestamp,
                    value=float(raw),
                )
            )

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

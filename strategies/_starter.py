"""_starter.py - tickweaver strategy boilerplate.

Copy this file (e.g. my_alpha.py) and edit on_bar / on_tick to your logic.
The yaml config under configs/ defines the backtest environment; this .py
file owns the trading parameters as module constants.

The engine injects three globals at module load:
  api    : StrategyAPI    - orders / positions / queries / helpers / viz
  context: StrategyContext - symbol / timeframe / bar_index
  + Side / OrderType / PositionSide enums (convenience)

Do NOT import or assign api/context yourself. The engine wires them.

Visualization (only takes effect when run with --viz):
  api.bind_indicator(name, indicator)  one-line binding for any streaming
                                       indicator from tickweaver.strategy.indicators.
                                       The engine auto-samples .value each bar
                                       and draws it on the chart. Multi-value
                                       indicators (BollingerBands, MACD) are
                                       decomposed into sub-lines (e.g.
                                       "BB.middle", "BB.upper", ...).
                                       Default panel comes from indicator.PANEL
                                       ("price" overlay vs sub-panel id).
                                       Idempotent: safe to call multiple times.
  api.plot(name, value)                low-level fallback when you compute a
                                       value externally and just want a line.
  api.comment(text)                    top-left chart text (multi-line OK).

All three are no-ops when chart_hook is disabled, so strategies stay valid
whether --viz is on or off.

Reference: strategies/_reference.md
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type stubs for IDE / linter only (not evaluated at runtime).
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


# ── trading parameters (edit here to tune) ──────────────────
UP_THRESHOLD = 0.01     # 1.0% bar-over-bar rise triggers entry
SIZE_PCT = 0.1          # 10% of available cash per entry


# ── module-level state (engine reload calls on_init to reset) ──
prev_close = 0.0
trade_count = 0


def on_init():
    """Called once at backtest start. Reset all module-level state here."""
    global prev_close, trade_count
    prev_close = 0.0
    trade_count = 0

    # Optional --viz: expose streaming indicators so they render on the chart.
    # Noop when --viz is off; remove the commented block to keep the file lean.
    #
    #   from tickweaver.strategy.indicators import EMA, RSI
    #   global ema_fast, rsi
    #   ema_fast = EMA(period=20)
    #   rsi      = RSI(period=14)
    #   api.bind_indicator("EMA 20", ema_fast)   # overlay on price (default)
    #   api.bind_indicator("RSI",    rsi)        # sub-panel (RSI.PANEL='rsi')

    api.log("strategy initialized")


def on_bar(bar):
    """Called after each bar closes. Edit this hook for bar-close signals."""
    global prev_close, trade_count

    if prev_close > 0 and api.is_flat():
        if bar.close > prev_close * (1.0 + UP_THRESHOLD):
            qty = api.size_from_cash_pct(SIZE_PCT, bar.close)
            api.market_buy(qty)
            trade_count += 1

    prev_close = bar.close


def on_tick(tick):
    """Called for every synthesized tick (optional).

    Use this for tick-level SL/TP, breakout triggers, or any logic that
    should react to sub-bar price moves. Orders submitted here fill on the
    next tick.
    """
    pass


def on_fill(fill):
    """Called immediately after each fill (optional)."""
    pass


def on_deinit():
    """Called once at backtest end (optional)."""
    api.log("strategy finished", trade_count=trade_count, final_equity=api.equity)

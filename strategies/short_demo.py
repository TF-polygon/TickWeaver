"""short_demo.py - RSI overbought 시 short open, oversold 시 close.

Phase F4 (dev/future_mode) — futures mode 데모 전략.

동작:
  - RSI > OVERBOUGHT 이고 FLAT 이면 market_sell -> short 포지션 진입.
  - RSI < OVERSOLD 이고 SHORT 보유 중이면 close_position -> 청산.

mode='futures' 에서만 정상 작동. mode='spot' 으로 돌리면 첫 SELL 호출에서
broker 가 SpotShortNotAllowedError 를 raise — Phase F1 가드의 의도된 동작.

실행:
  python scripts/run_backtest.py --strategy short_demo --config futures.yaml --viz

trading parameters (edit here to tune):
"""

from typing import TYPE_CHECKING

from tickweaver.strategy.indicators import RSI

if TYPE_CHECKING:
    # Type stubs for IDE / linter only — never executed at runtime.
    # FileStrategy injects these names into the module namespace.
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


# ── trading parameters (module constants) ───────────────────
RSI_PERIOD = 14
OVERBOUGHT = 70.0
OVERSOLD = 30.0
SIZE_PCT = 0.2          # 0.2 = 20% of available cash per entry


# ── state ───────────────────────────────────────────────────
rsi = None


def on_init() -> None:
    global rsi
    rsi = RSI(period=RSI_PERIOD)
    # Phase 4 viz: RSI는 sub-panel 에 표시 (RSI.PANEL = 'rsi').
    api.bind_indicator("RSI", rsi)


def on_bar(bar: "OHLCBar") -> None:
    rsi.update(bar.close)
    if not rsi.is_warm:
        return

    if rsi.value > OVERBOUGHT and api.is_flat():
        qty = api.size_from_cash_pct(SIZE_PCT, bar.close)
        if qty > 0:
            api.market_sell(qty)
            api.log("entry_short_overbought",
                    rsi=round(rsi.value, 2), price=bar.close)

    elif rsi.value < OVERSOLD and not api.is_flat():
        api.close_position()
        api.log("exit_short_oversold",
                rsi=round(rsi.value, 2), price=bar.close)


def on_fill(fill: "Fill") -> None:
    api.log(
        "fill",
        side=fill.side.name,
        price=round(fill.price, 2),
        qty=fill.qty,
        pnl_realized=round(fill.pnl_realized, 2),
    )


def on_deinit() -> None:
    api.log(
        "short_demo finished",
        final_equity=round(api.equity, 2),
        position_qty=api.position().qty,
    )

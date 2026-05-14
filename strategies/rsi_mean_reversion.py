"""rsi_mean_reversion.py - simple single-asset RSI mean reversion.

Logic:
  - Enter long when RSI dips below oversold threshold.
  - Exit when RSI crosses back above overbought threshold.
  - One position at a time (D3 single asset).

Lookahead protection is enforced by the engine: signals decided in on_bar
fill from the first tick of the NEXT bar.

Trading parameters (edit here to tune):
"""

from tickweaver.strategy.indicators import RSI


# ── trading parameters (module constants) ───────────────────
RSI_PERIOD = 14
OVERSOLD = 30.0
OVERBOUGHT = 70.0
SIZE_PCT = 0.2          # 0.2 = 20% of available cash per entry


# ── state ───────────────────────────────────────────────────
rsi = None


def on_init():
    global rsi
    rsi = RSI(period=RSI_PERIOD)
    # Phase 4 viz: expose RSI on its own sub-panel (RSI.PANEL == 'rsi').
    # Noop when --viz is off.
    api.bind_indicator("RSI", rsi)


def on_bar(bar):
    rsi.update(bar.close)
    if not rsi.is_warm:
        return

    if rsi.value < OVERSOLD and api.is_flat():
        qty = api.size_from_cash_pct(SIZE_PCT, bar.close)
        if qty > 0:
            api.market_buy(qty)
            api.log("entry_oversold", rsi=round(rsi.value, 2), price=bar.close)

    elif rsi.value > OVERBOUGHT and not api.is_flat():
        api.close_position()
        api.log("exit_overbought", rsi=round(rsi.value, 2), price=bar.close)


def on_fill(fill):
    api.log(
        "fill",
        side=fill.side.name,
        price=round(fill.price, 2),
        qty=fill.qty,
        pnl_realized=round(fill.pnl_realized, 2),
    )


def on_deinit():
    api.log(
        "rsi_mean_reversion finished",
        final_equity=round(api.equity, 2),
        position_qty=api.position().qty,
    )

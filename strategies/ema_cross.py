"""ema_cross.py - fast EMA / slow EMA cross entry + cross exit.

Reference: strategies/_reference.md
"""

from tickweaver.strategy.indicators import EMA


# ── trading parameters (module constants) ───────────────────
EMA_FAST = 12
EMA_SLOW = 26
SIZE_PCT = 0.2


# ── state ───────────────────────────────────────────────────
ema_fast = None
ema_slow = None
prev_diff = None


def on_init():
    global ema_fast, ema_slow, prev_diff
    ema_fast = EMA(period=EMA_FAST)
    ema_slow = EMA(period=EMA_SLOW)
    prev_diff = None
    # Phase 4 viz: expose both EMAs as overlay lines on the price panel.
    # Noop when --viz is off (chart_hook is None); strategy logic unchanged.
    api.bind_indicator("EMA fast", ema_fast)
    api.bind_indicator("EMA slow", ema_slow)


def on_bar(bar):
    global prev_diff

    ema_fast.update(bar.close)
    ema_slow.update(bar.close)
    if not (ema_fast.is_warm and ema_slow.is_warm):
        return

    diff = ema_fast.value - ema_slow.value
    if prev_diff is None:
        prev_diff = diff
        return

    crossed_up = prev_diff <= 0 and diff > 0
    crossed_down = prev_diff >= 0 and diff < 0

    if crossed_up and api.is_flat():
        qty = api.size_from_cash_pct(SIZE_PCT, bar.close)
        if qty > 0:
            api.market_buy(qty)
    elif crossed_down and not api.is_flat():
        api.close_position()

    prev_diff = diff


def on_deinit():
    api.log(
        "ema_cross finished",
        final_equity=api.equity,
        position_qty=api.position().qty,
    )

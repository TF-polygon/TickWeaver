"""ema_cross.py — fast EMA / slow EMA 크로스로 진입/청산.

reference: strategies/_reference.md §6.1
params (ema_cross.json): ema_fast, ema_slow, size_pct
"""

from tickweaver.strategy.indicators import EMA

ema_fast = None
ema_slow = None
prev_diff = None


def on_init():
    global ema_fast, ema_slow, prev_diff
    ema_fast = EMA(period=params.get("ema_fast", 12))
    ema_slow = EMA(period=params.get("ema_slow", 26))
    prev_diff = None


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
        size_pct = params.get("size_pct", 0.2)
        api.market_buy(api.size_from_cash_pct(size_pct, bar.close))
    elif crossed_down and not api.is_flat():
        api.close_position()

    prev_diff = diff


def on_deinit():
    api.log("ema_cross finished",
            final_equity=api.equity,
            position_qty=api.position().qty)

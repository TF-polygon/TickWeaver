"""ema_market_sl_tp.py - EMA cross entry + intra-bar market SL/TP exit.

Pattern 2 (on_bar entry + on_tick exit) reference. Entry signal is decided
on bar close. SL/TP are evaluated on every synthesized tick so exits can
fire inside a bar wick at the actual price the wick reached.

Trading parameters (edit here to tune):
"""

from tickweaver.strategy.indicators import EMA


# ── trading parameters (module constants) ───────────────────
FAST_PERIOD = 12
SLOW_PERIOD = 26
SL_PCT = 0.01           # 0.01 = -1.0% stop loss
TP_PCT = 0.015          # 0.015 = +1.5% take profit
SIZE_PCT = 0.2


# ── state ───────────────────────────────────────────────────
fast_ema = None
slow_ema = None
prev_fast = None
prev_slow = None

entry_price = None
sl_price = None
tp_price = None


def on_init():
    global fast_ema, slow_ema, prev_fast, prev_slow
    global entry_price, sl_price, tp_price
    fast_ema = EMA(period=FAST_PERIOD)
    slow_ema = EMA(period=SLOW_PERIOD)
    prev_fast = None
    prev_slow = None
    entry_price = None
    sl_price = None
    tp_price = None
    # Phase 4 viz: overlay both EMAs on the price panel. Noop when viz off.
    api.bind_indicator("EMA fast", fast_ema)
    api.bind_indicator("EMA slow", slow_ema)


def on_bar(bar):
    """Bar-close EMA cross detection. Order fills on next bar tick 1."""
    global prev_fast, prev_slow

    fast_ema.update(bar.close)
    slow_ema.update(bar.close)
    if not (fast_ema.is_warm and slow_ema.is_warm):
        return

    fast_v = float(fast_ema.value)
    slow_v = float(slow_ema.value)

    if prev_fast is not None and prev_slow is not None:
        cross_up = (prev_fast <= prev_slow) and (fast_v > slow_v)
        if cross_up and api.is_flat():
            size = api.size_from_cash_pct(SIZE_PCT, bar.close)
            if size > 0:
                api.market_buy(size)
                api.comment(
                    f"ema_x@{bar.close:.4f} fast={fast_v:.4f} slow={slow_v:.4f}"
                )

    prev_fast = fast_v
    prev_slow = slow_v


def on_tick(tick):
    """Per-tick SL/TP enforcement. Runs AFTER broker fills on this tick."""
    global entry_price, sl_price, tp_price

    if api.is_flat():
        entry_price = None
        sl_price = None
        tp_price = None
        return

    # First tick after buy fill: lock in entry + compute SL/TP
    if entry_price is None:
        pos = api.position()
        entry_price = float(pos.entry_price)
        sl_price = entry_price * (1.0 - SL_PCT)
        tp_price = entry_price * (1.0 + TP_PCT)
        api.comment(
            f"entry={entry_price:.4f}  sl={sl_price:.4f}  tp={tp_price:.4f}"
        )

    # SL first (conservative tie-break), then TP
    if tick.price <= sl_price:
        api.close_position()
        api.comment(f"SL hit @ {tick.price:.4f} (entry {entry_price:.4f})")
    elif tick.price >= tp_price:
        api.close_position()
        api.comment(f"TP hit @ {tick.price:.4f} (entry {entry_price:.4f})")

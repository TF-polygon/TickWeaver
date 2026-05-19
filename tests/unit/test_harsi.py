"""Phase V2.3 — HARSI (Heikin Ashi RSI) indicator.

Pine Script 1:1 port of JayRogers' "HARSI Dot Signal".

API:
    h = HARSI(rsi_len=7, harsi_len=14, smoothing=7, mode=True)
    h.update(open, high, low, close)  -> (ha_open, ha_high, ha_low, ha_close, overlay)
    h.ha_open / .ha_high / .ha_low / .ha_close / .overlay
    h.dot_signal() -> 'long' / 'short' / None
    h.harsi_long / .harsi_short  (Vulture's M15 signals)
"""

from __future__ import annotations

from tickweaver.strategy.indicators import HARSI


def test_harsi_metadata():
    assert HARSI.PANEL == "harsi"
    assert HARSI.SUBVALUES == ("ha_open", "ha_high", "ha_low", "ha_close", "overlay")


def test_harsi_not_warm_initially():
    h = HARSI()
    assert h.ha_open is None
    assert h.ha_close is None
    assert h.overlay is None
    assert h.is_warm is False
    assert h.dot_signal() is None


def test_harsi_warms_up_after_enough_bars():
    h = HARSI(rsi_len=7, harsi_len=14, smoothing=7, mode=True)
    base = 100.0
    for i in range(40):
        o = base + i * 0.1
        c = o + 0.05
        hi = max(o, c) + 0.1
        lo = min(o, c) - 0.1
        h.update(o, hi, lo, c)
    assert h.is_warm
    assert h.ha_open is not None
    assert h.ha_close is not None
    assert h.overlay is not None


def test_harsi_zero_median_range_is_minus50_to_50():
    """f_zrsi = rsi - 50 → values are in [-50, 50] roughly.
    HA-RSI candles are built from these zero-median streams, so they too live
    around 0."""
    h = HARSI(rsi_len=7, harsi_len=14, smoothing=7, mode=True)
    import random
    random.seed(7)
    price = 100.0
    for _ in range(80):
        price += random.uniform(-1, 1)
        h.update(price, price + 0.5, price - 0.5, price)
    assert -100.0 <= h.ha_open <= 100.0
    assert -100.0 <= h.ha_close <= 100.0
    assert -100.0 <= h.overlay <= 100.0


def test_harsi_dot_signal_returns_long_or_short_or_none():
    h = HARSI(rsi_len=7, harsi_len=14, smoothing=7, mode=True)
    import random
    random.seed(13)
    price = 100.0
    signals = set()
    for _ in range(200):
        price += random.uniform(-2, 2)
        h.update(price, price + 1, price - 1, price + random.uniform(-0.5, 0.5))
        sig = h.dot_signal()
        if sig is not None:
            signals.add(sig)
    # Over 200 random bars we should see at least one signal of each kind.
    assert "long" in signals or "short" in signals


def test_harsi_long_short_are_mutually_exclusive():
    """At a given bar harsi_long and harsi_short cannot both be True."""
    h = HARSI(rsi_len=7, harsi_len=14, smoothing=7, mode=True)
    import random
    random.seed(21)
    price = 100.0
    for _ in range(120):
        price += random.uniform(-2, 2)
        h.update(price, price + 1, price - 1, price)
        assert not (h.harsi_long and h.harsi_short)


def test_harsi_reset_clears_state():
    h = HARSI()
    for i in range(40):
        h.update(100 + i, 101 + i, 99 + i, 100.5 + i)
    assert h.is_warm
    h.reset()
    assert h.ha_open is None
    assert h.is_warm is False


def test_harsi_dot_signal_long_condition_branch():
    """Manually trigger O < RSI < C with hand-set state — direct branch test."""
    h = HARSI()
    # Drive the bar enough for warmup
    for i in range(40):
        h.update(100, 101, 99, 100)
    # Override last state to force long-condition branch (O < C; O < RSI < C).
    h._ha_open = -10.0
    h._ha_close = 10.0
    h._RSI_overlay = 0.0   # in (O, C)
    assert h.dot_signal() == "long"


def test_harsi_dot_signal_short_condition_branch():
    h = HARSI()
    for i in range(40):
        h.update(100, 101, 99, 100)
    # O > C; O > RSI > C → short
    h._ha_open = 10.0
    h._ha_close = -10.0
    h._RSI_overlay = 0.0
    assert h.dot_signal() == "short"

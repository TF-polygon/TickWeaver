"""SuperTrend indicator — unit tests.

Behavioral invariants (robust against exact band arithmetic):
- warms only after ATR has `period` bars;
- a sustained uptrend → direction +1 with the line below price (support);
- a sharp reversal flips direction and moves the line to the other side.
"""

from __future__ import annotations

import pytest

from tickweaver.strategy.indicators import SuperTrend


class _Bar:
    def __init__(self, high, low, close):
        self.high, self.low, self.close = high, low, close


def _uptrend(st: SuperTrend, n: int, start: float = 100.0, step: float = 4.0) -> float:
    c = start
    for _ in range(n):
        c += step
        st.update(c + 2, c - 2, c)
    return c


def _downtrend(st: SuperTrend, n: int, start: float = 300.0, step: float = 4.0) -> float:
    c = start
    for _ in range(n):
        c -= step
        st.update(c + 2, c - 2, c)
    return c


def test_warmup_needs_atr_period():
    st = SuperTrend(period=3, multiplier=2.0)
    assert st.update(110, 90, 100) is None
    assert st.update(112, 92, 102) is None
    assert not st.is_warm
    v = st.update(114, 94, 104)   # 3rd bar → ATR warm → SuperTrend seeds
    assert v is not None
    assert st.is_warm
    assert st.direction in (1, -1)


def test_uptrend_is_bullish_line_below_price():
    st = SuperTrend(period=3, multiplier=2.0)
    last_close = _uptrend(st, 15)
    assert st.direction == 1
    assert st.value < last_close          # line sits below price (support)


def test_downtrend_is_bearish_line_above_price():
    st = SuperTrend(period=3, multiplier=2.0)
    last_close = _downtrend(st, 15)
    assert st.direction == -1
    assert st.value > last_close          # line sits above price (resistance)


def test_flip_down_on_crash():
    st = SuperTrend(period=3, multiplier=2.0)
    c = _uptrend(st, 15)
    assert st.direction == 1
    crash = c - 60.0
    st.update(c, crash - 2, crash)        # sharp drop below the lower band
    assert st.direction == -1
    assert st.value > crash


def test_flip_up_on_rally():
    st = SuperTrend(period=3, multiplier=2.0)
    c = _downtrend(st, 15)
    assert st.direction == -1
    rally = c + 60.0
    st.update(rally + 2, c, rally)        # sharp rally above the upper band
    assert st.direction == 1
    assert st.value < rally


def test_reset_clears_state():
    st = SuperTrend(period=3)
    _uptrend(st, 6)
    assert st.is_warm
    st.reset()
    assert not st.is_warm
    assert st.value is None
    assert st.direction is None


def test_update_bar_matches_update():
    st = SuperTrend(period=2, multiplier=2.0)
    assert st.update_bar(_Bar(110, 90, 100)) is None   # ATR not warm yet
    v = st.update_bar(_Bar(112, 92, 102))              # 2nd bar warms ATR
    assert v is not None
    assert st.is_warm


def test_panel_is_price_overlay():
    assert SuperTrend.PANEL == "price"
    assert SuperTrend.SUBVALUES is None


def test_param_validation():
    with pytest.raises(ValueError):
        SuperTrend(period=0)
    with pytest.raises(ValueError):
        SuperTrend(multiplier=0)

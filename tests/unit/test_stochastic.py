"""Phase V2.1 — Stochastic Oscillator (K, D)."""

from __future__ import annotations

import pytest

from tickweaver.strategy.indicators import Stochastic


def test_stochastic_metadata():
    assert Stochastic.PANEL == "stoch"
    assert Stochastic.SUBVALUES == ("K", "D")


def test_stochastic_not_warm_initially():
    s = Stochastic(period=14, k_smooth=3, d_smooth=3)
    assert s.K is None
    assert s.D is None
    assert s.is_warm is False


def test_stochastic_warmup_takes_period_plus_smoothing():
    s = Stochastic(period=5, k_smooth=3, d_smooth=3)
    # 5 bars to fill the period, +k_smooth-1 for the K-SMA, +d_smooth-1 for D.
    for i in range(5):
        s.update(high=10 + i, low=8 + i, close=9 + i)
    # K should not be ready yet (still need 2 more for k_smooth=3)
    assert s.K is None or s.D is None
    # After 5 + (k_smooth-1) + (d_smooth-1) = 9 bars, both K and D should be set.
    for i in range(5, 12):
        s.update(high=10 + i, low=8 + i, close=9 + i)
    assert s.is_warm
    assert s.K is not None
    assert s.D is not None


def test_stochastic_k_range_zero_to_hundred():
    """%K is bounded in [0, 100]."""
    s = Stochastic(period=5, k_smooth=3, d_smooth=3)
    import random
    random.seed(42)
    for _ in range(50):
        low = random.uniform(80, 100)
        high = low + random.uniform(1, 5)
        close = random.uniform(low, high)
        s.update(high=high, low=low, close=close)
    assert s.K is not None
    assert 0.0 <= s.K <= 100.0
    assert 0.0 <= s.D <= 100.0


def test_stochastic_close_at_period_high_pushes_k_high():
    """When the latest close is the highest of the lookback, %K should be ~100
    (before smoothing flattens it). Use small smoothing periods to be visible."""
    s = Stochastic(period=5, k_smooth=1, d_smooth=1)
    # Build a clearly-uptrending series so the latest close is at the top.
    for i in range(10):
        s.update(high=100 + i, low=99 + i, close=100 + i)
    assert s.is_warm
    # latest close = 109 == highest_high of last 5 bars (109)
    # lowest_low of last 5 bars = 104
    # raw K = (109 - 104) / (109 - 104) * 100 = 100
    assert s.K == pytest.approx(100.0)


def test_stochastic_close_at_period_low_pushes_k_low():
    s = Stochastic(period=5, k_smooth=1, d_smooth=1)
    for i in range(10):
        s.update(high=110 - i, low=109 - i, close=109 - i)
    assert s.is_warm
    # latest close = 100 = lowest_low; raw K = 0
    assert s.K == pytest.approx(0.0)


def test_stochastic_reset_clears_state():
    s = Stochastic(period=5, k_smooth=3, d_smooth=3)
    for i in range(20):
        s.update(high=10 + i, low=8 + i, close=9 + i)
    assert s.is_warm
    s.reset()
    assert s.K is None
    assert s.D is None
    assert s.is_warm is False


def test_stochastic_value_alias_returns_k():
    """`indicator.value` convention returns the primary line (K)."""
    s = Stochastic(period=5, k_smooth=1, d_smooth=1)
    for i in range(10):
        s.update(high=100 + i, low=99 + i, close=100 + i)
    assert s.value == s.K

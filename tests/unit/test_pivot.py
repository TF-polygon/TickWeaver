"""Phase V2.2 — Swing-point Pivot indicator.

period=N means a bar is a pivot high if the previous N bars and next N bars
all have lower highs. Symmetric for pivot low.

API:
  pivot.update(high, low)
  pivot.last_pivot_high / .second_pivot_high
  pivot.last_pivot_low  / .second_pivot_low
  pivot.is_higher_low() / .is_lower_high()   <- Vulture's _pivot_low/_pivot_high
"""

from __future__ import annotations

from tickweaver.strategy.indicators import Pivot


def test_pivot_metadata():
    assert Pivot.PANEL == "price"


def test_pivot_not_warm_initially():
    p = Pivot(period=2)
    assert p.last_pivot_high is None
    assert p.last_pivot_low is None
    assert p.is_higher_low() is False
    assert p.is_lower_high() is False


def test_pivot_high_detected_after_2period_plus_1_bars():
    """With period=2 a swing high is identified once we have seen 5 bars
    (2 before + 1 mid + 2 after). The middle bar of [..2,..2] becomes the
    pivot once the right-side window is complete."""
    p = Pivot(period=2)
    # bars: 100, 102, 110, 105, 103   (mid 110 is the swing high)
    highs = [100, 102, 110, 105, 103]
    lows = [99, 101, 109, 104, 102]
    for h, l in zip(highs, lows):
        p.update(h, l)
    assert p.last_pivot_high == 110


def test_pivot_low_detected():
    p = Pivot(period=2)
    # mid bar low = 90 (swing low)
    highs = [110, 105, 95, 100, 108]
    lows = [108, 100, 90, 95, 103]
    for h, l in zip(highs, lows):
        p.update(h, l)
    assert p.last_pivot_low == 90


def test_pivot_second_history():
    """When a new pivot is confirmed, the previous one becomes the 'second'."""
    p = Pivot(period=2)
    # Two swing highs in sequence:
    #   bars 0..4 → swing high at idx 2 (value 110)
    #   bars 4..8 → swing high at idx 6 (value 115)
    seq = [
        (100, 99),   # 0
        (102, 101),  # 1
        (110, 109),  # 2  ← first pivot high
        (105, 104),  # 3
        (103, 102),  # 4
        (108, 107),  # 5
        (115, 114),  # 6  ← second pivot high
        (112, 111),  # 7
        (110, 109),  # 8
    ]
    for h, l in seq:
        p.update(h, l)
    assert p.last_pivot_high == 115
    assert p.second_pivot_high == 110


def test_is_higher_low_signals_uptrend_in_lows():
    p = Pivot(period=2)
    # Two swing lows: first at 90, second at 95 (higher) → uptrend.
    seq = [
        (110, 108),  # 0
        (105, 100),  # 1
        (95, 90),    # 2 ← pivot low 90
        (100, 95),   # 3
        (108, 103),  # 4
        (107, 102),  # 5
        (101, 95),   # 6 ← pivot low 95 (higher than 90)
        (105, 100),  # 7
        (110, 105),  # 8
    ]
    for h, l in seq:
        p.update(h, l)
    assert p.last_pivot_low == 95
    assert p.second_pivot_low == 90
    assert p.is_higher_low() is True
    assert p.is_lower_high() is False  # no second pivot high


def test_is_lower_high_signals_downtrend_in_highs():
    p = Pivot(period=2)
    # Two swing highs: first 120 (bar 2), second 115 (bar 6, lower).
    seq = [
        (105, 100),  # 0
        (110, 105),  # 1
        (120, 115),  # 2 ← first pivot high
        (110, 105),  # 3
        (105, 100),  # 4
        (108, 103),  # 5
        (115, 110),  # 6 ← second pivot high (lower than 120)
        (110, 105),  # 7
        (105, 100),  # 8
    ]
    for h, l in seq:
        p.update(h, l)
    assert p.last_pivot_high == 115
    assert p.second_pivot_high == 120
    assert p.is_lower_high() is True


def test_reset_clears_state():
    p = Pivot(period=2)
    for h, l in [(100, 99), (102, 101), (110, 109), (105, 104), (103, 102)]:
        p.update(h, l)
    assert p.last_pivot_high == 110
    p.reset()
    assert p.last_pivot_high is None
    assert p.is_higher_low() is False

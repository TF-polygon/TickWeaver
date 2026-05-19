"""Phase V3 — BarAggregator (M1 → N-minute resampler).

OHLCBar.timestamp 는 ccxt convention 으로 open_ts. 즉 bar의 close_ts =
open_ts + source_tf.

aggregator.update(m1_bar) → 누적, target boundary 도달 시 완성된 bar 반환.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tickweaver.core.types import OHLCBar
from tickweaver.strategy.timeframe import BarAggregator


def _m1(minute: int, hour: int = 0, open_: float = 100.0, high: float = 101.0,
        low: float = 99.0, close: float = 100.5, volume: float = 1.0) -> OHLCBar:
    return OHLCBar(
        timestamp=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=hour, minutes=minute),
        open=open_, high=high, low=low, close=close,
        volume=volume, symbol="T", timeframe="1m",
    )


def test_invalid_target_minutes_raises():
    with pytest.raises(Exception):
        BarAggregator(target_minutes=0)
    with pytest.raises(Exception):
        BarAggregator(target_minutes=-1)


def test_m15_emits_only_on_boundary():
    a = BarAggregator(target_minutes=15)
    # First 14 M1 bars (minutes 0..13) → no emit yet.
    for m in range(14):
        out = a.update(_m1(minute=m))
        assert out is None
    # 15th M1 (minute=14, close_ts = 00:15) → emit.
    out = a.update(_m1(minute=14))
    assert out is not None
    assert out.timeframe == "15m"


def test_m15_ohlc_computed_correctly():
    a = BarAggregator(target_minutes=15)
    bars = [
        _m1(minute=0,  open_=100, high=101, low=99,  close=100.5, volume=1),
        _m1(minute=1,  open_=100.5, high=102, low=100, close=101, volume=2),
        _m1(minute=2,  open_=101, high=101.5, low=100.5, close=101, volume=1),
        # ... fill the rest
    ]
    for m in range(3, 14):
        bars.append(_m1(minute=m, open_=101, high=103, low=99, close=102, volume=1))
    bars.append(_m1(minute=14, open_=102, high=104, low=101, close=103, volume=3))

    out = None
    for b in bars:
        result = a.update(b)
        if result is not None:
            out = result

    assert out is not None
    assert out.open == 100        # first M1's open
    assert out.close == 103       # last M1's close
    assert out.high == 104        # max of all
    assert out.low == 99          # min of all
    assert out.volume == 1+2+1+1*11+3   # sum (15 M1 bars)


def test_m15_subsequent_window():
    """After the first M15 emits, the next 15 M1 bars produce another M15."""
    a = BarAggregator(target_minutes=15)
    for m in range(15):
        a.update(_m1(minute=m))
    # next M1: minute=15 → start of new window. Should not emit until minute=29.
    for m in range(15, 29):
        out = a.update(_m1(minute=m))
        assert out is None
    out = a.update(_m1(minute=29))
    assert out is not None


def test_h1_emits_only_at_hour_boundary():
    a = BarAggregator(target_minutes=60)
    # 60 M1 bars over hour=0, minutes 0..59. Emit on the 60th (minute=59).
    for m in range(59):
        out = a.update(_m1(minute=m, hour=0))
        assert out is None
    out = a.update(_m1(minute=59, hour=0))
    assert out is not None
    assert out.timeframe == "60m"


def test_d1_emits_on_day_boundary():
    a = BarAggregator(target_minutes=1440)
    # Drive 24h of M1 bars. Emit on the last one (23:59).
    # Sparse drive to keep the test fast: emit must be None for any bar that
    # is NOT (hour=23, minute=59), and the emit happens exactly once at that
    # bar.
    saw_emit = False
    for h in range(24):
        for m in range(60):
            out = a.update(_m1(minute=m, hour=h))
            if h == 23 and m == 59:
                assert out is not None
                saw_emit = True
            else:
                assert out is None
    assert saw_emit


def test_reset_clears_partial_window():
    a = BarAggregator(target_minutes=15)
    a.update(_m1(minute=0))
    a.update(_m1(minute=1))
    a.reset()
    # Next bar at minute=14 should NOT emit because the window is fresh —
    # only bars from minute=14 (well, in reality from "now") are accumulated.
    # The aggregator simply starts a new window with this bar.
    out = a.update(_m1(minute=14, open_=200, high=201, low=199, close=200.5))
    # close_ts of minute=14 is 00:15 which IS a 15-min boundary, so it emits
    # as a single-bar M15 (degenerate). That's expected behaviour after reset.
    assert out is not None
    # OHLC equals the single source bar's OHLC.
    assert out.open == 200
    assert out.high == 201
    assert out.low == 199
    assert out.close == 200.5


def test_value_property_returns_last_emitted():
    a = BarAggregator(target_minutes=15)
    for m in range(15):
        a.update(_m1(minute=m, close=100 + m))
    assert a.last_completed is not None
    assert a.last_completed.close == 114


def test_pending_property_returns_in_progress_state():
    a = BarAggregator(target_minutes=15)
    a.update(_m1(minute=0, open_=100, high=101, low=99, close=100.5))
    a.update(_m1(minute=1, open_=100.5, high=102, low=100, close=101))
    p = a.pending
    assert p is not None
    assert p.open == 100      # first
    assert p.close == 101     # latest
    assert p.high == 102      # max so far

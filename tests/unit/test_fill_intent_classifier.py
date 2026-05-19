"""Phase F3 (dev/future_mode) — viz 4-way fill classifier.

Each fill is one of: open_long / close_long / open_short / close_short.
A reverse fill (e.g. SELL while LONG with qty > position.qty in futures)
emits BOTH a close (long) and an open (short) at the same timestamp/price.
"""

from __future__ import annotations

import pandas as pd

from tickweaver.core.types import Fill, Side
from tickweaver.viz.live_window import _classify_fills_by_intent


def _fill(side: Side, price: float, qty: float = 1.0, idx: int = 0) -> Fill:
    return Fill(
        order_id=f"X-{idx}",
        symbol="T",
        side=side,
        qty=qty,
        price=price,
        fee=0.0,
        timestamp=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=idx),
    )


def _ts(idx: int) -> pd.Timestamp:
    return pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=idx)


# ─────────────────────────────────────────────────────────
# Single long round-trip
# ─────────────────────────────────────────────────────────
def test_long_round_trip():
    fills = [
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.SELL, 110.0, 1.0, idx=1),
    ]
    r = _classify_fills_by_intent(fills)
    assert r["open_long"] == [(_ts(0), 100.0)]
    assert r["close_long"] == [(_ts(1), 110.0)]
    assert r["open_short"] == []
    assert r["close_short"] == []


# ─────────────────────────────────────────────────────────
# Single short round-trip (futures)
# ─────────────────────────────────────────────────────────
def test_short_round_trip():
    fills = [
        _fill(Side.SELL, 100.0, 1.0, idx=0),
        _fill(Side.BUY, 90.0, 1.0, idx=1),
    ]
    r = _classify_fills_by_intent(fills)
    assert r["open_short"] == [(_ts(0), 100.0)]
    assert r["close_short"] == [(_ts(1), 90.0)]
    assert r["open_long"] == []
    assert r["close_long"] == []


# ─────────────────────────────────────────────────────────
# Partial close
# ─────────────────────────────────────────────────────────
def test_long_partial_close_then_full_close():
    fills = [
        _fill(Side.BUY, 100.0, 2.0, idx=0),
        _fill(Side.SELL, 110.0, 1.0, idx=1),  # partial close
        _fill(Side.SELL, 115.0, 1.0, idx=2),  # finish close
    ]
    r = _classify_fills_by_intent(fills)
    assert r["open_long"] == [(_ts(0), 100.0)]
    assert r["close_long"] == [(_ts(1), 110.0), (_ts(2), 115.0)]


# ─────────────────────────────────────────────────────────
# Pyramiding (same-side adds)
# ─────────────────────────────────────────────────────────
def test_long_pyramiding_buy_adds_are_open_long():
    fills = [
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.BUY, 102.0, 1.0, idx=1),
        _fill(Side.SELL, 105.0, 2.0, idx=2),
    ]
    r = _classify_fills_by_intent(fills)
    assert r["open_long"] == [(_ts(0), 100.0), (_ts(1), 102.0)]
    assert r["close_long"] == [(_ts(2), 105.0)]


# ─────────────────────────────────────────────────────────
# Position reverse (LONG -> SHORT in one fill, futures)
# ─────────────────────────────────────────────────────────
def test_long_to_short_reverse_emits_close_and_open():
    """SELL qty > position.qty while LONG: close LONG + open SHORT in one
    fill timestamp. Both should be emitted."""
    fills = [
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.SELL, 95.0, 2.0, idx=1),  # close 1.0 + open short 1.0
    ]
    r = _classify_fills_by_intent(fills)
    assert r["open_long"] == [(_ts(0), 100.0)]
    assert r["close_long"] == [(_ts(1), 95.0)]
    assert r["open_short"] == [(_ts(1), 95.0)]
    assert r["close_short"] == []


def test_short_to_long_reverse_emits_close_and_open():
    fills = [
        _fill(Side.SELL, 100.0, 1.0, idx=0),
        _fill(Side.BUY, 105.0, 2.0, idx=1),  # close short 1.0 + open long 1.0
    ]
    r = _classify_fills_by_intent(fills)
    assert r["open_short"] == [(_ts(0), 100.0)]
    assert r["close_short"] == [(_ts(1), 105.0)]
    assert r["open_long"] == [(_ts(1), 105.0)]


# ─────────────────────────────────────────────────────────
# Unclosed position (last fill is entry, no exit)
# ─────────────────────────────────────────────────────────
def test_unclosed_long_only_has_open_marker():
    fills = [_fill(Side.BUY, 100.0, 1.0, idx=0)]
    r = _classify_fills_by_intent(fills)
    assert r["open_long"] == [(_ts(0), 100.0)]
    assert r["close_long"] == []
    assert r["open_short"] == []
    assert r["close_short"] == []


def test_unclosed_short_only_has_open_marker():
    fills = [_fill(Side.SELL, 100.0, 1.0, idx=0)]
    r = _classify_fills_by_intent(fills)
    assert r["open_short"] == [(_ts(0), 100.0)]


# ─────────────────────────────────────────────────────────
# Empty
# ─────────────────────────────────────────────────────────
def test_empty_fills_returns_empty_lists():
    r = _classify_fills_by_intent([])
    assert r == {
        "open_long": [],
        "close_long": [],
        "open_short": [],
        "close_short": [],
    }


# ─────────────────────────────────────────────────────────
# Determinism: same fill list -> same result
# ─────────────────────────────────────────────────────────
def test_classifier_is_deterministic():
    fills = [
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.SELL, 105.0, 1.0, idx=1),
        _fill(Side.SELL, 103.0, 1.0, idx=2),   # open short
        _fill(Side.BUY, 99.0, 1.0, idx=3),     # close short
    ]
    r1 = _classify_fills_by_intent(fills)
    r2 = _classify_fills_by_intent(fills)
    assert r1 == r2

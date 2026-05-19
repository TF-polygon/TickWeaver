"""Phase V8 — _make_pair_lines (per-position entry→close pair lines).

마틴게일 같은 same-side add 에서 entry 마다 별도 pair line. 종점은 동일
close fill, 시점은 각자 다른 entry fill.
"""

from __future__ import annotations

import itertools

import pandas as pd

from tickweaver.core.types import Fill, Side
from tickweaver.viz.live_window import _make_pair_lines


_coid = itertools.count(1)


def _fill(side: Side, price: float, qty: float = 1.0, idx: int = 0) -> Fill:
    n = next(_coid)
    return Fill(
        order_id=f"ORD-{n}", symbol="T", side=side, qty=qty, price=price, fee=0.0,
        timestamp=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=idx),
    )


def test_simple_long_round_trip_one_pair():
    pairs = _make_pair_lines([
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.SELL, 110.0, 1.0, idx=1),
    ])
    assert len(pairs) == 1
    # V8b: 5-tuple (e_ts, e_p, x_ts, x_p, side) — side="buy" for a long entry.
    e_ts, e_p, x_ts, x_p, side = pairs[0]
    assert e_p == 100.0
    assert x_p == 110.0
    assert side == "buy"


def test_martingale_three_adds_yields_three_pairs():
    """BUY*3 → SELL all → 3 pair lines, common close, distinct entries."""
    pairs = _make_pair_lines([
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.BUY, 99.0, 2.0, idx=1),
        _fill(Side.BUY, 98.0, 4.0, idx=2),
        _fill(Side.SELL, 105.0, 7.0, idx=3),    # close all
    ])
    assert len(pairs) == 3
    # exits all share the close ts/price
    assert all(p[3] == 105.0 for p in pairs)
    assert all(p[2] == pairs[0][2] for p in pairs)
    # entry prices are the three distinct fills
    entry_prices = sorted(p[1] for p in pairs)
    assert entry_prices == [98.0, 99.0, 100.0]


def test_partial_close_fifo_matching():
    """BUY q=2 → BUY q=2 → SELL q=3 closes 2 + 1 (FIFO).
    Result: 2 pair lines from the partial close at t=2.
    Remaining 1 of the second BUY is still open (no pair until next close)."""
    pairs = _make_pair_lines([
        _fill(Side.BUY, 100.0, 2.0, idx=0),
        _fill(Side.BUY, 99.0, 2.0, idx=1),
        _fill(Side.SELL, 105.0, 3.0, idx=2),    # close 2 + 1 (partial)
    ])
    # 2 pairs emitted (first entry fully closed + second entry partially)
    assert len(pairs) == 2
    assert pairs[0][1] == 100.0   # first entry
    assert pairs[1][1] == 99.0    # second entry


def test_short_round_trip():
    pairs = _make_pair_lines([
        _fill(Side.SELL, 100.0, 1.0, idx=0),
        _fill(Side.BUY, 95.0, 1.0, idx=1),
    ])
    assert len(pairs) == 1
    assert pairs[0][1] == 100.0
    assert pairs[0][3] == 95.0


def test_short_martingale_yields_per_position_lines():
    pairs = _make_pair_lines([
        _fill(Side.SELL, 100.0, 1.0, idx=0),
        _fill(Side.SELL, 101.0, 2.0, idx=1),
        _fill(Side.BUY, 98.0, 3.0, idx=2),     # close all 3
    ])
    assert len(pairs) == 2
    # common close
    assert all(p[3] == 98.0 for p in pairs)
    # distinct entries
    assert {pairs[0][1], pairs[1][1]} == {100.0, 101.0}


def test_reverse_fill_pairs_old_position_then_starts_new():
    """SELL qty=3 on LONG qty=1 closes the 1 (pair) and opens SHORT 2."""
    pairs = _make_pair_lines([
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.SELL, 95.0, 3.0, idx=1),
        _fill(Side.BUY, 90.0, 2.0, idx=2),
    ])
    assert len(pairs) == 2
    # First pair: long round trip
    assert pairs[0][1] == 100.0 and pairs[0][3] == 95.0
    # Second pair: short opened by leftover at 95, closed at 90
    assert pairs[1][1] == 95.0 and pairs[1][3] == 90.0


def test_unclosed_position_yields_no_pair():
    pairs = _make_pair_lines([
        _fill(Side.BUY, 100.0, 1.0, idx=0),
    ])
    assert pairs == []


def test_empty_fills_returns_empty():
    assert _make_pair_lines([]) == []

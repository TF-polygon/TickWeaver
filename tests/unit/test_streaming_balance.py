"""streaming-viz — realized balance per closed trade (pure, headless).

build_balance_by_close returns equity-per-trade points: [start, close_1, ...],
one dict per closed position (trade_no, timestamp, pnl, balance). X = close
count, 0 = start at initial_cash. Consistent with the position table
(same cum_pnl / cum_fee accounting).
"""

from __future__ import annotations

import pandas as pd

from tickweaver.core.types import Fill, Side
from tickweaver.viz.streaming import build_balance_by_close


def _fill(side: Side, price: float, qty: float, fee: float, sec: int) -> Fill:
    return Fill(
        order_id=str(sec),
        symbol="T",
        side=side,
        qty=qty,
        price=price,
        fee=fee,
        timestamp=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(seconds=sec),
    )


def _bal(pts):
    return [round(p["balance"], 4) for p in pts]


def test_no_fills_is_just_start_point():
    pts = build_balance_by_close([], initial_cash=10_000.0)
    assert len(pts) == 1
    assert pts[0] == {"trade_no": 0, "timestamp": None, "pnl": None, "balance": 10_000.0}


def test_open_only_has_no_close_point():
    fills = [_fill(Side.BUY, 100.0, 1.0, 0.5, 0)]
    pts = build_balance_by_close(fills, initial_cash=5_000.0)
    assert len(pts) == 1               # only the start point
    assert pts[0]["balance"] == 5_000.0


def test_single_round_trip_long_profit():
    fills = [
        _fill(Side.BUY, 100.0, 1.0, 0.1, 0),
        _fill(Side.SELL, 110.0, 1.0, 0.1, 10),
    ]
    pts = build_balance_by_close(fills, initial_cash=10_000.0)
    assert _bal(pts) == [10_000.0, 10_009.8]   # start, after close#1 (gross +10, fees .2)
    c1 = pts[1]
    assert c1["trade_no"] == 1
    assert round(c1["pnl"], 4) == 10.0         # gross PnL
    assert c1["timestamp"] == fills[1].timestamp


def test_short_round_trip_profit():
    fills = [
        _fill(Side.SELL, 110.0, 1.0, 0.1, 0),
        _fill(Side.BUY, 100.0, 1.0, 0.1, 10),
    ]
    assert _bal(build_balance_by_close(fills, initial_cash=1_000.0)) == [1_000.0, 1_009.8]


def test_one_point_per_close_with_metadata():
    fills = [
        _fill(Side.BUY, 100.0, 1.0, 0.1, 0),
        _fill(Side.SELL, 90.0, 1.0, 0.1, 10),   # close#1: gross -10
        _fill(Side.BUY, 95.0, 2.0, 0.2, 20),
        _fill(Side.SELL, 100.0, 2.0, 0.2, 30),  # close#2: gross +10
    ]
    pts = build_balance_by_close(fills, initial_cash=10_000.0)
    assert _bal(pts) == [10_000.0, 9_989.8, 9_999.4]
    assert [p["trade_no"] for p in pts] == [0, 1, 2]
    assert round(pts[1]["pnl"], 4) == -10.0
    assert round(pts[2]["pnl"], 4) == 10.0

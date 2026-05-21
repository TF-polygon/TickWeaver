"""Issue 3 Step 5a — build_marker_tooltips 검증.

핵심 불변식:
- `_classify_fills_by_intent` 와 1:1 매칭 (같은 intent 의 i 번째 marker 가
  같은 fill 의 같은 marker).
- Order # 가 build_position_history 와 동일 (진입 fill 순으로 1, 2, 3 ...).
- Reverse fill 은 close marker + open marker 2 개로 분할.
- 마틴게일 close 의 closed_orders 는 FIFO 매칭된 N 개 Order # list.
"""

from __future__ import annotations

import itertools

import pandas as pd

from tickweaver.analytics.positions import (
    build_marker_tooltips,
    build_position_history,
)
from tickweaver.core.types import Fill, Side
from tickweaver.viz.live_window import _classify_fills_by_intent


_coid = itertools.count(1)


def _fill(side: Side, price: float, qty: float = 1.0, idx: int = 0) -> Fill:
    n = next(_coid)
    return Fill(
        order_id=f"ORD-{n}",
        symbol="BTC/USDT:USDT",
        side=side,
        qty=qty,
        price=price,
        fee=0.0,
        timestamp=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=idx),
    )


# ──────────────────────────────────────────────────────────
# 기본 케이스
# ──────────────────────────────────────────────────────────


def test_empty_fills_yields_empty_groups():
    result = build_marker_tooltips([])
    assert result == {
        "open_long": [],
        "close_long": [],
        "open_short": [],
        "close_short": [],
    }


def test_simple_long_round_trip_one_open_one_close():
    fills = [
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.SELL, 110.0, 1.0, idx=1),
    ]
    result = build_marker_tooltips(fills, leverage=1.0)
    assert len(result["open_long"]) == 1
    assert len(result["close_long"]) == 1
    assert len(result["open_short"]) == 0
    assert len(result["close_short"]) == 0
    # Open
    op = result["open_long"][0]
    assert op["intent"] == "open_long"
    assert op["order_no"] == 1
    assert op["price"] == 100.0
    assert op["margin"] == 100.0
    # Close
    cl = result["close_long"][0]
    assert cl["intent"] == "close_long"
    assert cl["closed_orders"] == [1]
    assert cl["pnl"] == 10.0   # (110 - 100) * 1
    assert cl["price"] == 110.0


def test_simple_short_round_trip():
    fills = [
        _fill(Side.SELL, 100.0, 1.0, idx=0),
        _fill(Side.BUY, 95.0, 1.0, idx=1),
    ]
    result = build_marker_tooltips(fills, leverage=1.0)
    assert len(result["open_short"]) == 1
    assert len(result["close_short"]) == 1
    op = result["open_short"][0]
    assert op["order_no"] == 1
    assert op["margin"] == 100.0
    cl = result["close_short"][0]
    assert cl["closed_orders"] == [1]
    assert cl["pnl"] == 5.0   # (100 - 95) * 1


# ──────────────────────────────────────────────────────────
# 마틴게일 — 한 close marker 에 N 개 Order #
# ──────────────────────────────────────────────────────────


def test_long_martingale_close_has_all_matched_orders():
    """Buy*3 → Sell qty 7 (전부 청산). 한 close marker 에 3 Order # 매칭."""
    fills = [
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.BUY, 99.0, 2.0, idx=1),
        _fill(Side.BUY, 98.0, 4.0, idx=2),
        _fill(Side.SELL, 105.0, 7.0, idx=3),
    ]
    result = build_marker_tooltips(fills, leverage=1.0)
    assert len(result["open_long"]) == 3
    assert len(result["close_long"]) == 1
    # 각 open 의 Order #
    assert [m["order_no"] for m in result["open_long"]] == [1, 2, 3]
    # 한 close 가 3 Order # 매칭
    cl = result["close_long"][0]
    assert cl["closed_orders"] == [1, 2, 3]
    # PnL 합 = 5 + 12 + 28 = 45
    assert cl["pnl"] == 45.0


def test_short_martingale_close_has_all_matched_orders():
    fills = [
        _fill(Side.SELL, 100.0, 1.0, idx=0),
        _fill(Side.SELL, 101.0, 2.0, idx=1),
        _fill(Side.BUY, 98.0, 3.0, idx=2),
    ]
    result = build_marker_tooltips(fills, leverage=1.0)
    assert len(result["open_short"]) == 2
    assert len(result["close_short"]) == 1
    assert [m["order_no"] for m in result["open_short"]] == [1, 2]
    cl = result["close_short"][0]
    assert cl["closed_orders"] == [1, 2]
    assert cl["pnl"] == 8.0   # 2 + 6


# ──────────────────────────────────────────────────────────
# Reverse fill — 한 broker fill 이 close marker + open marker
# ──────────────────────────────────────────────────────────


def test_reverse_fill_emits_close_and_open_markers():
    """Buy q=1 → Sell q=3 → close 1 long + open 2 short.

    한 broker fill 이 close_long marker + open_short marker 2 개 동시 emit.
    """
    fills = [
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.SELL, 95.0, 3.0, idx=1),
    ]
    result = build_marker_tooltips(fills, leverage=1.0)
    assert len(result["open_long"]) == 1
    assert len(result["close_long"]) == 1
    assert len(result["open_short"]) == 1
    assert len(result["close_short"]) == 0
    # Close long: Order #1 매칭, PnL = -5
    cl = result["close_long"][0]
    assert cl["closed_orders"] == [1]
    assert cl["pnl"] == -5.0
    # Open short: 새 Order #2, leftover qty 2
    op = result["open_short"][0]
    assert op["order_no"] == 2
    assert op["margin"] == 95.0 * 2 / 1.0   # 190


# ──────────────────────────────────────────────────────────
# Cross-consistency: build_position_history 와 Order # 일치
# ──────────────────────────────────────────────────────────


def test_order_no_consistent_with_build_position_history():
    """두 함수의 같은 Order # 는 같은 진입 fill 을 가리킴."""
    fills = [
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.BUY, 99.0, 2.0, idx=1),
        _fill(Side.SELL, 105.0, 3.0, idx=2),
    ]
    history = build_position_history(fills, leverage=1.0)
    tooltips = build_marker_tooltips(fills, leverage=1.0)
    # history 의 Long row Order # 들과 tooltip 의 open_long Order # 들이 같음
    history_long_orders = [r.order_no for r in history if r.side == "Long"]
    tooltip_long_orders = [m["order_no"] for m in tooltips["open_long"]]
    assert history_long_orders == tooltip_long_orders == [1, 2]


def test_intent_counts_match_classify_fills_by_intent():
    """build_marker_tooltips 의 각 intent 길이가 _classify_fills_by_intent 와 동일."""
    fills = [
        _fill(Side.BUY, 100.0, 1.0, idx=0),
        _fill(Side.BUY, 99.0, 2.0, idx=1),
        _fill(Side.SELL, 105.0, 3.0, idx=2),
        _fill(Side.SELL, 110.0, 1.0, idx=3),
        _fill(Side.BUY, 108.0, 2.0, idx=4),   # reverse: close short + open long
    ]
    tooltips = build_marker_tooltips(fills, leverage=1.0)
    classified = _classify_fills_by_intent(fills)
    for intent in ("open_long", "close_long", "open_short", "close_short"):
        assert len(tooltips[intent]) == len(classified[intent]), (
            f"intent={intent}: tooltips={len(tooltips[intent])} "
            f"classified={len(classified[intent])}"
        )


# ──────────────────────────────────────────────────────────
# Margin / leverage
# ──────────────────────────────────────────────────────────


def test_margin_uses_leverage():
    fills = [_fill(Side.BUY, 100.0, 2.0, idx=0)]
    result = build_marker_tooltips(fills, leverage=10.0)
    assert result["open_long"][0]["margin"] == 20.0   # 100 * 2 / 10


def test_pnl_short_has_correct_sign():
    """Short PnL = entry - exit, gain on price drop."""
    fills = [
        _fill(Side.SELL, 100.0, 1.0, idx=0),
        _fill(Side.BUY, 90.0, 1.0, idx=1),
    ]
    result = build_marker_tooltips(fills, leverage=1.0)
    assert result["close_short"][0]["pnl"] == 10.0

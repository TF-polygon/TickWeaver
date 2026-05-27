"""Issue 4 — build_position_history FIFO 매칭 + PnL 분배 + Holding Bars 검증."""

from __future__ import annotations

import itertools

import pandas as pd
import pytest

from tickweaver.analytics.positions import PositionRow, build_position_history
from tickweaver.core.types import Fill, Side


_coid = itertools.count(1)


def _fill(
    side: Side, price: float, qty: float = 1.0, idx: int = 0, fee: float = 0.0
) -> Fill:
    """편의 헬퍼. idx 는 시간 슬롯 (시간당 1 step). fee 는 그 fill 의 수수료."""
    n = next(_coid)
    return Fill(
        order_id=f"ORD-{n}",
        symbol="BTC/USDT:USDT",
        side=side,
        qty=qty,
        price=price,
        fee=fee,
        timestamp=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=idx),
    )


# ──────────────────────────────────────────────────────────
# 기본 케이스
# ──────────────────────────────────────────────────────────


def test_empty_fills_yields_no_rows():
    assert build_position_history([]) == []


def test_simple_long_round_trip_two_rows():
    """Buy 1 → Sell 1 → 2 rows (Long, Close)."""
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0),
            _fill(Side.SELL, 110.0, 1.0, idx=1),
        ],
        leverage=1.0,
    )
    assert len(rows) == 2
    # Open row
    assert rows[0].side == "Long"
    assert rows[0].order_no == 1
    assert rows[0].entry_price == 100.0
    assert rows[0].margin == 100.0  # 100 * 1 / 1
    assert rows[0].pnl is None
    assert rows[0].cum_pnl is None
    # Close row
    assert rows[1].side == "Close"
    assert rows[1].order_no == 1
    assert rows[1].entry_price == 110.0  # close 시 entry_price = exit price (해당 fill price)
    assert rows[1].margin is None
    assert rows[1].pnl == 10.0  # (110 - 100) * 1
    assert rows[1].cum_pnl == 10.0


def test_simple_short_round_trip():
    """Sell 1 → Buy 1 → 2 rows (Short, Close). Short 의 PnL 은 (entry - exit)."""
    rows = build_position_history(
        [
            _fill(Side.SELL, 100.0, 1.0, idx=0),
            _fill(Side.BUY, 95.0, 1.0, idx=1),
        ],
        leverage=1.0,
    )
    assert len(rows) == 2
    assert rows[0].side == "Short"
    assert rows[0].order_no == 1
    assert rows[0].margin == 100.0
    assert rows[1].side == "Close"
    assert rows[1].order_no == 1
    assert rows[1].pnl == 5.0  # (100 - 95) * 1
    assert rows[1].cum_pnl == 5.0


# ──────────────────────────────────────────────────────────
# 마틴게일 / 분할 close
# ──────────────────────────────────────────────────────────


def test_long_martingale_three_adds_yields_three_closes_fifo():
    """Buy*3 (qty 1,2,4) → Sell qty 7 → 6 rows (3 Long + 3 Close).

    한 close fill 이 FIFO 로 N 개 Close row 로 분할. 각 Close 의
    Order # 는 매칭된 진입의 Order #.
    """
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0),
            _fill(Side.BUY, 99.0, 2.0, idx=1),
            _fill(Side.BUY, 98.0, 4.0, idx=2),
            _fill(Side.SELL, 105.0, 7.0, idx=3),  # close all
        ],
        leverage=1.0,
    )
    assert len(rows) == 6
    # Open rows (Order # 1, 2, 3)
    assert [r.side for r in rows[:3]] == ["Long", "Long", "Long"]
    assert [r.order_no for r in rows[:3]] == [1, 2, 3]
    assert [r.entry_price for r in rows[:3]] == [100.0, 99.0, 98.0]
    # Close rows (FIFO: Order # 1 → 2 → 3)
    assert [r.side for r in rows[3:]] == ["Close", "Close", "Close"]
    assert [r.order_no for r in rows[3:]] == [1, 2, 3]
    assert [r.entry_price for r in rows[3:]] == [105.0, 105.0, 105.0]
    # 모든 Close 의 timestamp 가 같은 close fill 의 ts
    assert all(r.timestamp == rows[3].timestamp for r in rows[3:])
    # PnL 분배: 매칭된 qty 별 개별 계산
    assert rows[3].pnl == 5.0   # (105 - 100) * 1
    assert rows[4].pnl == 12.0  # (105 - 99) * 2
    assert rows[5].pnl == 28.0  # (105 - 98) * 4
    # Cum. PnL 누적
    assert rows[3].cum_pnl == 5.0
    assert rows[4].cum_pnl == 17.0
    assert rows[5].cum_pnl == 45.0


def test_short_martingale_yields_per_order_closes():
    """Sell*2 → Buy all → 2 Short + 2 Close."""
    rows = build_position_history(
        [
            _fill(Side.SELL, 100.0, 1.0, idx=0),
            _fill(Side.SELL, 101.0, 2.0, idx=1),
            _fill(Side.BUY, 98.0, 3.0, idx=2),
        ],
        leverage=1.0,
    )
    assert len(rows) == 4
    assert [r.side for r in rows] == ["Short", "Short", "Close", "Close"]
    assert [r.order_no for r in rows] == [1, 2, 1, 2]
    # Short PnL = (entry - exit) * qty
    assert rows[2].pnl == 2.0   # (100 - 98) * 1
    assert rows[3].pnl == 6.0   # (101 - 98) * 2
    assert rows[2].cum_pnl == 2.0
    assert rows[3].cum_pnl == 8.0


def test_partial_close_fifo_matching():
    """Buy q=2 → Buy q=2 → Sell q=3 closes 2+1 (FIFO). order #2 잔여 1."""
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 2.0, idx=0),
            _fill(Side.BUY, 99.0, 2.0, idx=1),
            _fill(Side.SELL, 105.0, 3.0, idx=2),
        ],
        leverage=1.0,
    )
    assert len(rows) == 4
    assert [r.side for r in rows] == ["Long", "Long", "Close", "Close"]
    assert [r.order_no for r in rows] == [1, 2, 1, 2]
    assert rows[2].pnl == 10.0   # (105 - 100) * 2 — order #1 full close
    assert rows[3].pnl == 6.0    # (105 - 99) * 1 — order #2 partial (1 unit)


# ──────────────────────────────────────────────────────────
# Reverse fill (close + 새 진입 한 fill 에)
# ──────────────────────────────────────────────────────────


def test_reverse_fill_closes_then_opens_new():
    """Buy q=1 → Sell q=3 closes 1 long, leftover 2 opens short → 4 rows."""
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0),
            _fill(Side.SELL, 95.0, 3.0, idx=1),
            _fill(Side.BUY, 90.0, 2.0, idx=2),
        ],
        leverage=1.0,
    )
    assert len(rows) == 4
    assert [r.side for r in rows] == ["Long", "Close", "Short", "Close"]
    assert [r.order_no for r in rows] == [1, 1, 2, 2]
    assert rows[1].pnl == -5.0   # (95 - 100) * 1 — long lose
    assert rows[3].pnl == 10.0   # (95 - 90) * 2 — short win, (entry - exit) * qty
    assert rows[1].cum_pnl == -5.0
    assert rows[3].cum_pnl == 5.0   # -5 + 10


# ──────────────────────────────────────────────────────────
# 미청산 / margin
# ──────────────────────────────────────────────────────────


def test_unclosed_position_yields_only_open_row():
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0),
        ],
        leverage=1.0,
    )
    assert len(rows) == 1
    assert rows[0].side == "Long"
    assert rows[0].order_no == 1
    assert rows[0].pnl is None
    assert rows[0].cum_pnl is None
    assert rows[0].holding_bars is None


def test_margin_uses_leverage():
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 2.0, idx=0),
        ],
        leverage=10.0,
    )
    assert rows[0].margin == 20.0   # 100 * 2 / 10


# ──────────────────────────────────────────────────────────
# Holding Bars
# ──────────────────────────────────────────────────────────


def test_holding_bars_computed_when_timestamps_given():
    """Open at idx=0 (= bar 0), Close at idx=3 (= bar 3) → holding_bars = 3."""
    bar_ts = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0),
            _fill(Side.SELL, 110.0, 1.0, idx=3),
        ],
        leverage=1.0,
        bar_timestamps=bar_ts,
    )
    assert rows[0].holding_bars is None  # open row
    assert rows[1].holding_bars == 3      # close row, 3 bars later


def test_holding_bars_none_when_no_bar_timestamps():
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0),
            _fill(Side.SELL, 110.0, 1.0, idx=1),
        ],
        leverage=1.0,
    )
    assert rows[1].holding_bars is None


def test_holding_bars_for_martingale_close_each_row():
    """마틴게일 N add cycle 의 분할 close 각각의 holding_bars 는 해당 Order # 진입 시점부터 close 시점까지."""
    bar_ts = pd.date_range("2024-01-01", periods=20, freq="1h", tz="UTC")
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0),
            _fill(Side.BUY, 99.0, 2.0, idx=5),
            _fill(Side.SELL, 110.0, 3.0, idx=10),  # close both
        ],
        leverage=1.0,
        bar_timestamps=bar_ts,
    )
    assert len(rows) == 4
    # rows[2] = Close of Order #1 (entry idx=0, exit idx=10) → 10
    assert rows[2].holding_bars == 10
    # rows[3] = Close of Order #2 (entry idx=5, exit idx=10) → 5
    assert rows[3].holding_bars == 5


# ──────────────────────────────────────────────────────────
# Fee 분배 (Polish Work A)
#   - 각 row 가 자기 fill 의 fee 를 표시:
#       open row  = open fill fee (의 그 row 가 연 qty 비율)
#       close row = close fill fee * matched_qty / fill.qty
#   - Cum. Fee = open/close 가리지 않고 row 순 running sum
# ──────────────────────────────────────────────────────────


def test_fee_single_round_trip_per_row():
    """Buy(fee 0.05) → Sell(fee 0.055): open row 0.05, close row 0.055."""
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0, fee=0.05),
            _fill(Side.SELL, 110.0, 1.0, idx=1, fee=0.055),
        ],
        leverage=1.0,
    )
    assert rows[0].fee == pytest.approx(0.05)       # open row 자기 fee
    assert rows[0].cum_fee == pytest.approx(0.05)
    assert rows[1].fee == pytest.approx(0.055)      # close row 자기 fee
    assert rows[1].cum_fee == pytest.approx(0.105)  # 누적


def test_fee_martingale_split_close_distributes_close_fill_fee():
    """Buy*2 → Sell qty2(fee 0.095): 두 Close row 가 close fee 를 qty 비율 분배."""
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0, fee=0.05),
            _fill(Side.BUY, 90.0, 1.0, idx=1, fee=0.045),
            _fill(Side.SELL, 95.0, 2.0, idx=2, fee=0.095),
        ],
        leverage=1.0,
    )
    assert len(rows) == 4
    assert rows[0].fee == pytest.approx(0.05)     # Long o1
    assert rows[1].fee == pytest.approx(0.045)    # Long o2
    # close fill fee 0.095 / qty 2 = 0.0475 per matched unit
    assert rows[2].fee == pytest.approx(0.0475)   # Close o1
    assert rows[3].fee == pytest.approx(0.0475)   # Close o2
    # Cum. Fee running sum
    assert rows[0].cum_fee == pytest.approx(0.05)
    assert rows[1].cum_fee == pytest.approx(0.095)
    assert rows[2].cum_fee == pytest.approx(0.1425)
    assert rows[3].cum_fee == pytest.approx(0.19)


def test_fee_partial_close_uses_close_fill_qty():
    """Buy qty2(fee 0.10) → Sell qty1(fee 0.055): close row = 0.055 (fill.qty=1)."""
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 2.0, idx=0, fee=0.10),
            _fill(Side.SELL, 110.0, 1.0, idx=1, fee=0.055),
        ],
        leverage=1.0,
    )
    assert len(rows) == 2
    assert rows[0].fee == pytest.approx(0.10)      # open row full open fee
    assert rows[1].fee == pytest.approx(0.055)     # close fill fee * 1/1
    assert rows[1].cum_fee == pytest.approx(0.155)


def test_fee_reverse_fill_splits_close_and_open_portions():
    """Buy q1(fee 0.05) → Sell q3(fee 0.15): close 1 (0.05) + open short 2 (0.10)."""
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0, fee=0.05),
            _fill(Side.SELL, 110.0, 3.0, idx=1, fee=0.15),
        ],
        leverage=1.0,
    )
    assert len(rows) == 3
    assert [r.side for r in rows] == ["Long", "Close", "Short"]
    assert rows[0].fee == pytest.approx(0.05)      # open long
    # sell fill fee 0.15 / qty 3 = 0.05 per unit
    assert rows[1].fee == pytest.approx(0.05)      # close 1 unit
    assert rows[2].fee == pytest.approx(0.10)      # open short 2 units (reverse)
    # 분배 총합 = sell fill fee 0.15 보존 (close 0.05 + open 0.10)
    assert rows[1].fee + rows[2].fee == pytest.approx(0.15)
    assert rows[2].cum_fee == pytest.approx(0.20)  # 0.05 + 0.05 + 0.10


def test_fee_zero_yields_zero_not_none():
    """fee=0 fill → close/open row fee 는 0.0 (None 아님)."""
    rows = build_position_history(
        [
            _fill(Side.BUY, 100.0, 1.0, idx=0, fee=0.0),
            _fill(Side.SELL, 110.0, 1.0, idx=1, fee=0.0),
        ],
        leverage=1.0,
    )
    assert rows[0].fee == 0.0
    assert rows[1].fee == 0.0
    assert rows[1].cum_fee == 0.0

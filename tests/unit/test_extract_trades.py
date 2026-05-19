"""Phase F4.2 — extract_trades reverse-fill handling.

The original implementation dropped the leftover quantity when a single
fill closed an existing position and then reversed direction (e.g. SELL
qty=3 hitting a LONG qty=1 closes 1 and opens a SHORT 2 — the leftover
SHORT 2 was silently ignored). This caused the viz pair line to mismatch
the corresponding markers because trade entry/exit prices stopped
pairing with the actual fills after the first reverse.
"""

from __future__ import annotations

import itertools

import pandas as pd

from tickweaver.analytics.trades import extract_trades
from tickweaver.core.types import Fill, Side


_coid = itertools.count(1)


def _fill(side: Side, price: float, qty: float = 1.0, idx: int = 0,
          fee: float = 0.0) -> Fill:
    n = next(_coid)
    return Fill(
        order_id=f"ORD-{n}",
        symbol="T",
        side=side,
        qty=qty,
        price=price,
        fee=fee,
        timestamp=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=idx),
    )


# ─────────────────────────────────────────────────────────
# Baseline (must keep working): pure long round trip
# ─────────────────────────────────────────────────────────
def test_simple_long_round_trip_yields_one_trade():
    trades = extract_trades([
        _fill(Side.BUY, 100.0, qty=1.0, idx=0),
        _fill(Side.SELL, 110.0, qty=1.0, idx=1),
    ])
    assert len(trades) == 1
    assert trades[0].side == Side.BUY
    assert trades[0].entry_price == 100.0
    assert trades[0].exit_price == 110.0
    assert trades[0].qty == 1.0


# ─────────────────────────────────────────────────────────
# Reverse fill (the bug this phase fixes)
# ─────────────────────────────────────────────────────────
def test_close_plus_reverse_in_one_fill_yields_two_trades():
    """SELL qty=3 hitting LONG qty=1 should yield:
      trade 1: LONG close (qty 1, entry 100, exit 99.8)
      and start a SHORT qty 2 @ 99.8 which the next BUY closes.
    Without this fix the leftover SHORT 2 was silently dropped and the
    next BUY @ 99 was matched against nothing, breaking the pair-line."""
    trades = extract_trades([
        _fill(Side.BUY, 100.0, qty=1.0, idx=0),
        _fill(Side.SELL, 99.8, qty=3.0, idx=1),    # close 1 + open short 2
        _fill(Side.BUY, 99.0, qty=2.0, idx=2),     # close short 2
    ])
    assert len(trades) == 2
    # Trade 1: LONG round trip
    assert trades[0].side == Side.BUY
    assert trades[0].qty == 1.0
    assert trades[0].entry_price == 100.0
    assert trades[0].exit_price == 99.8
    # Trade 2: SHORT round trip
    assert trades[1].side == Side.SELL
    assert trades[1].qty == 2.0
    assert trades[1].entry_price == 99.8
    assert trades[1].exit_price == 99.0


def test_short_to_long_reverse_in_one_fill():
    """Symmetric: BUY qty=3 hitting SHORT qty=1 → close 1 + open LONG 2."""
    trades = extract_trades([
        _fill(Side.SELL, 100.0, qty=1.0, idx=0),
        _fill(Side.BUY, 100.2, qty=3.0, idx=1),    # close 1 + open long 2
        _fill(Side.SELL, 101.0, qty=2.0, idx=2),
    ])
    assert len(trades) == 2
    assert trades[0].side == Side.SELL
    assert trades[0].entry_price == 100.0
    assert trades[0].exit_price == 100.2
    assert trades[1].side == Side.BUY
    assert trades[1].entry_price == 100.2
    assert trades[1].qty == 2.0
    assert trades[1].exit_price == 101.0


def test_consecutive_reverses_yield_correct_trade_count():
    """Continuous zig-zag pattern of future_demo:
      BUY 1, SELL 3 (close+reverse short 2), BUY 5 (close+reverse long 3),
      SELL 7 (close+reverse short 4), BUY 4 (close short 4)
    → 4 trades."""
    trades = extract_trades([
        _fill(Side.BUY, 100.0, qty=1.0, idx=0),
        _fill(Side.SELL, 99.8, qty=3.0, idx=1),
        _fill(Side.BUY, 100.0, qty=5.0, idx=2),
        _fill(Side.SELL, 99.8, qty=7.0, idx=3),
        _fill(Side.BUY, 99.6, qty=4.0, idx=4),
    ])
    assert len(trades) == 4
    # 첫 LONG → 99.8 short reverse → 100 long reverse → 99.8 short reverse → 99.6 close
    assert [t.side for t in trades] == [Side.BUY, Side.SELL, Side.BUY, Side.SELL]
    # Check qty: 1, 2 (=3-1), 3 (=5-2), 4 (=7-3)
    assert [t.qty for t in trades] == [1.0, 2.0, 3.0, 4.0]


# ─────────────────────────────────────────────────────────
# PnL preserved through reverse path
# ─────────────────────────────────────────────────────────
def test_reverse_trades_have_correct_signed_pnl():
    trades = extract_trades([
        _fill(Side.BUY, 100.0, qty=1.0, idx=0),
        _fill(Side.SELL, 105.0, qty=3.0, idx=1),    # close LONG 1 @ +5; open SHORT 2 @ 105
        _fill(Side.BUY, 100.0, qty=2.0, idx=2),     # close SHORT 2 @ +5 each
    ])
    assert len(trades) == 2
    # Trade 1: LONG +5 * 1 = +5
    assert trades[0].pnl == 5.0
    # Trade 2: SHORT (105 - 100) * 2 = +10
    assert trades[1].pnl == 10.0


# ─────────────────────────────────────────────────────────
# Partial close (no reverse) — existing behaviour must keep working
# ─────────────────────────────────────────────────────────
def test_partial_close_does_not_create_phantom_short_trade():
    """SELL qty=0.5 on LONG qty=1 → trade 0.5 closed, 0.5 LONG remains.
    No new SHORT trade should appear."""
    trades = extract_trades([
        _fill(Side.BUY, 100.0, qty=1.0, idx=0),
        _fill(Side.SELL, 105.0, qty=0.5, idx=1),    # partial close
        _fill(Side.SELL, 110.0, qty=0.5, idx=2),    # finish
    ])
    assert len(trades) == 2
    assert all(t.side == Side.BUY for t in trades)
    assert [t.qty for t in trades] == [0.5, 0.5]


# ─────────────────────────────────────────────────────────
# Phase V6 — first_entry_price for martingale add visualization
# ─────────────────────────────────────────────────────────
def test_trade_first_entry_price_equals_initial_fill_for_simple_round_trip():
    """When there is no add, first_entry_price == entry_price (the single fill price)."""
    trades = extract_trades([
        _fill(Side.BUY, 100.0, qty=1.0, idx=0),
        _fill(Side.SELL, 110.0, qty=1.0, idx=1),
    ])
    assert len(trades) == 1
    assert trades[0].first_entry_price == 100.0
    assert trades[0].entry_price == 100.0


def test_first_entry_price_stays_at_first_fill_through_same_side_adds():
    """Pyramiding / martingale adds change entry_price (weighted average) but
    first_entry_price must stay at the very first add's price — the pair
    line in viz uses this so the line's left endpoint sits on the first
    Open Long marker, not the moving average."""
    trades = extract_trades([
        _fill(Side.BUY, 100.0, qty=1.0, idx=0),    # first
        _fill(Side.BUY, 99.0, qty=1.0, idx=1),     # add
        _fill(Side.BUY, 98.0, qty=2.0, idx=2),     # add
        _fill(Side.SELL, 102.0, qty=4.0, idx=3),   # close all
    ])
    assert len(trades) == 1
    # first_entry_price = 100.0 (very first fill)
    assert trades[0].first_entry_price == 100.0
    # entry_price = weighted average ≠ 100
    expected_avg = (100.0 * 1 + 99.0 * 1 + 98.0 * 2) / 4
    assert trades[0].entry_price == pytest.approx(expected_avg)
    assert trades[0].entry_price != 100.0


def test_first_entry_price_resets_for_new_cycle_after_reverse():
    """After a reverse fill creates a new trade, that trade's first_entry_price
    starts at the reverse-fill price."""
    trades = extract_trades([
        _fill(Side.BUY, 100.0, qty=1.0, idx=0),
        _fill(Side.SELL, 95.0, qty=3.0, idx=1),    # close 1 + open short 2 @ 95
        _fill(Side.BUY, 90.0, qty=2.0, idx=2),     # close short
    ])
    assert len(trades) == 2
    # First trade: long round trip
    assert trades[0].first_entry_price == 100.0
    # Second trade: opened by reverse leg at 95
    assert trades[1].first_entry_price == 95.0


# Add pytest import for approx (used above).
import pytest  # noqa: E402,F401

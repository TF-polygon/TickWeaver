"""streaming-viz unit #5a — progress-driven reveal (pure, headless).

Covers the synchronization core for "전부 실시간": as the replay advances,
fill markers / indicator samples / position-table rows reveal up to the
current replay timestamp.
"""

from __future__ import annotations

import pandas as pd

from tickweaver.core.types import OHLCBar, Tick
from tickweaver.viz.streaming import TickReplayer, revealed_count


def _bar(idx: int) -> OHLCBar:
    return OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC")
        + pd.Timedelta(hours=idx),
        open=100.0, high=105.0, low=95.0, close=100.0,
        volume=1.0, symbol="T", timeframe="1h",
    )


def _ticks_for_bar(bar_index: int, prices: list[float]) -> list[Tick]:
    base = pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=bar_index)
    return [
        Tick(timestamp=base + pd.Timedelta(seconds=i), price=float(p),
             bar_index=bar_index, tick_index_in_bar=i, symbol="T")
        for i, p in enumerate(prices)
    ]


def _ts(seconds: int) -> pd.Timestamp:
    return pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(seconds=seconds)


# ── current_tick_ts ────────────────────────────────────────────────────────
def test_current_tick_ts_none_before_advance():
    r = TickReplayer(ticks=_ticks_for_bar(0, [100.0, 101.0]), bars=[(0, _bar(0))])
    assert r.current_tick_ts is None


def test_current_tick_ts_tracks_last_consumed():
    ticks = _ticks_for_bar(0, [100.0, 101.0, 102.0])
    r = TickReplayer(ticks=ticks, bars=[(0, _bar(0))])
    r.advance()
    assert r.current_tick_ts == ticks[0].timestamp
    r.advance()
    assert r.current_tick_ts == ticks[1].timestamp


# ── revealed_count ─────────────────────────────────────────────────────────
def test_revealed_count_inclusive_and_partial():
    ts = [_ts(0), _ts(10), _ts(20), _ts(30)]
    assert revealed_count(ts, _ts(20)) == 3        # <= is inclusive
    assert revealed_count(ts, _ts(15)) == 2        # between 10 and 20


def test_revealed_count_before_all_is_zero():
    ts = [_ts(10), _ts(20)]
    assert revealed_count(ts, _ts(5)) == 0


def test_revealed_count_after_all_is_full():
    ts = [_ts(10), _ts(20)]
    assert revealed_count(ts, _ts(99)) == 2


def test_revealed_count_none_now_is_zero():
    assert revealed_count([_ts(10)], None) == 0


def test_revealed_count_empty_is_zero():
    assert revealed_count([], _ts(10)) == 0


# ── integration: fills reveal monotonically as the replay advances ──────────
def test_fills_reveal_tracks_replay_progress():
    # 2 bars, fills land on specific tick timestamps
    ticks = _ticks_for_bar(0, [100.0, 101.0, 102.0]) + _ticks_for_bar(1, [102.0, 103.0])
    bars = [(0, _bar(0)), (1, _bar(1))]
    r = TickReplayer(ticks=ticks, bars=bars)

    # a fill at bar 0 tick#1, another at bar 1 tick#0
    fill_ts = [ticks[1].timestamp, ticks[3].timestamp]

    revealed_seq = []
    while r.advance():
        revealed_seq.append(revealed_count(fill_ts, r.current_tick_ts))

    # monotonic non-decreasing, ends fully revealed
    assert revealed_seq == sorted(revealed_seq)
    assert revealed_seq[-1] == 2
    # at the moment the first fill's tick is consumed, count becomes 1
    assert revealed_seq[1] == 1   # after 2nd advance (tick index 1)

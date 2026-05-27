"""streaming-viz unit #1 — tick replay pipeline (pure, headless).

Covers goal §3.A "캔들 빌더" + "전체 재생":
- PartialBar: open fixed, high=running max, low=running min, close=last tick.
- TickReplayer: consume recorded ticks in order, bar boundaries by bar_index,
  final candle OHLC == recorded bar OHLC (C1-C4 invariants), full replay covers
  every bar with no tick cap.
"""

from __future__ import annotations

import pandas as pd

from tickweaver.core.types import OHLCBar, Tick
from tickweaver.viz import EventRecorder
from tickweaver.viz.streaming import PartialBar, TickReplayer


# ── builders ─────────────────────────────────────────────────────────────
def _bar(idx: int, o: float, h: float, l: float, c: float) -> OHLCBar:
    return OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC")
        + pd.Timedelta(hours=idx),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=1.0,
        symbol="T",
        timeframe="1h",
    )


def _ticks_for_bar(bar_index: int, prices: list[float]) -> list[Tick]:
    """Build a bar's tick sequence. Mirrors the engine: bar_index fixed,
    tick_index_in_bar = 0..n-1, one tick per price in order."""
    base = pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=bar_index)
    return [
        Tick(
            timestamp=base + pd.Timedelta(seconds=i),
            price=float(p),
            bar_index=bar_index,
            tick_index_in_bar=i,
            symbol="T",
        )
        for i, p in enumerate(prices)
    ]


# ── PartialBar ───────────────────────────────────────────────────────────
def test_partial_bar_open_fixed_high_low_close_grow():
    pb = PartialBar(bar_index=0, timestamp=_bar(0, 100, 100, 100, 100).timestamp,
                    open=100.0, high=100.0, low=100.0, close=100.0)
    pb.update(105.0)   # up
    assert pb.open == 100.0 and pb.high == 105.0 and pb.low == 100.0 and pb.close == 105.0
    pb.update(95.0)    # down — open still fixed, low drops, close follows
    assert pb.open == 100.0 and pb.high == 105.0 and pb.low == 95.0 and pb.close == 95.0
    pb.update(101.0)   # within range — only close moves
    assert pb.open == 100.0 and pb.high == 105.0 and pb.low == 95.0 and pb.close == 101.0


# ── single-bar incremental build ───────────────────────────────────────────
def test_replayer_single_bar_incremental_ohlc():
    prices = [100.0, 103.0, 98.0, 101.0, 99.0]   # open, .., close
    ticks = _ticks_for_bar(0, prices)
    bars = [(0, _bar(0, 100.0, 103.0, 98.0, 99.0))]
    r = TickReplayer(ticks=ticks, bars=bars)

    # consume tick by tick; open never moves, close == last consumed price
    fed: list[float] = []
    while r.advance():
        fed.append(r.current_bar.close)
        assert r.current_bar.open == 100.0            # open never moves
    assert fed == prices                              # close tracked each tick
    cb = r.current_bar
    assert cb.open == 100.0
    assert cb.high == 103.0
    assert cb.low == 98.0
    assert cb.close == 99.0   # last tick == close


def test_replayer_partial_high_low_track_running_extremes():
    prices = [100.0, 102.0, 101.0, 97.0, 100.0]
    ticks = _ticks_for_bar(0, prices)
    r = TickReplayer(ticks=ticks, bars=[(0, _bar(0, 100, 102, 97, 100))])

    expected = [
        (100, 100, 100),  # after open tick
        (102, 100, 102),  # high up
        (102, 100, 101),  # within
        (102, 97, 97),    # low down
        (102, 97, 100),   # within
    ]
    i = 0
    while r.advance():
        cb = r.current_bar
        h, l, c = expected[i]
        assert (cb.high, cb.low, cb.close) == (h, l, c), f"tick {i}"
        i += 1
    assert i == len(prices)


# ── final candle == recorded bar OHLC (C1-C4 invariants) ───────────────────
def test_replayer_final_candle_matches_recorded_ohlc():
    # ticks honoring C1 (first=open), C2 (last=close), C3/C4 (touch H/L)
    prices = [100.0, 110.0, 90.0, 105.0]
    ticks = _ticks_for_bar(0, prices)
    bar = _bar(0, 100.0, 110.0, 90.0, 105.0)
    r = TickReplayer(ticks=ticks, bars=[(0, bar)])
    while r.advance():
        pass
    cb = r.current_bar
    assert (cb.open, cb.high, cb.low, cb.close) == (
        bar.open, bar.high, bar.low, bar.close
    )


# ── bar boundaries + ordering ──────────────────────────────────────────────
def test_replayer_bar_boundaries_and_order():
    t0 = _ticks_for_bar(0, [100.0, 105.0, 102.0])
    t1 = _ticks_for_bar(1, [102.0, 108.0, 107.0])
    t2 = _ticks_for_bar(2, [107.0, 101.0, 103.0])
    bars = [
        (0, _bar(0, 100, 105, 100, 102)),
        (1, _bar(1, 102, 108, 102, 107)),
        (2, _bar(2, 107, 107, 101, 103)),
    ]
    r = TickReplayer(ticks=t0 + t1 + t2, bars=bars)

    # after first bar's 3 ticks, no completed bar yet (current = bar 0)
    r.advance(); r.advance(); r.advance()
    assert r.completed_bars == []
    assert r.current_bar.bar_index == 0

    # first tick of bar 1 finalizes bar 0
    r.advance()
    assert [b.bar_index for b in r.completed_bars] == [0]
    assert r.current_bar.bar_index == 1
    assert r.completed_bars[0].close == 102.0   # bar 0 close

    while r.advance():
        pass
    assert [b.bar_index for b in r.completed_bars] == [0, 1]
    assert r.current_bar.bar_index == 2
    # all_bars = completed + current, in order
    assert [b.bar_index for b in r.all_bars] == [0, 1, 2]


# ── full replay covers everything, then done ───────────────────────────────
def test_replayer_full_replay_covers_all_bars():
    n_bars = 12
    all_ticks: list[Tick] = []
    bars = []
    for i in range(n_bars):
        base = 100.0 + i
        all_ticks += _ticks_for_bar(i, [base, base + 5, base - 5, base + 1])
        bars.append((i, _bar(i, base, base + 5, base - 5, base + 1)))

    r = TickReplayer(ticks=all_ticks, bars=bars)
    assert not r.done
    steps = 0
    while r.advance():
        steps += 1
    assert r.done
    assert steps == len(all_ticks)   # every tick consumed exactly once
    assert r.n_consumed == len(all_ticks)
    assert len(r.all_bars) == n_bars
    assert [b.bar_index for b in r.all_bars] == list(range(n_bars))


def test_replayer_uses_bar_timestamp_for_x():
    bar = _bar(3, 100, 101, 99, 100)
    ticks = _ticks_for_bar(3, [100.0, 101.0, 100.0])
    r = TickReplayer(ticks=ticks, bars=[(3, bar)])
    r.advance()
    assert r.current_bar.timestamp == bar.timestamp


def test_replayer_empty_ticks_is_done():
    r = TickReplayer(ticks=[], bars=[])
    assert r.done
    assert not r.advance()
    assert r.current_bar is None
    assert r.all_bars == []


# ── no tick cap: full record for full replay ───────────────────────────────
def test_recorder_unbounded_keeps_all_ticks():
    rec = EventRecorder(max_ticks=None)
    assert rec.ticks.maxlen is None
    n = 1000
    for i in range(n):
        rec.on_tick(
            Tick(
                timestamp=pd.Timestamp("2024-01-01", tz="UTC")
                + pd.Timedelta(seconds=i),
                price=100.0 + i,
                bar_index=i // 10,
                tick_index_in_bar=i % 10,
            )
        )
    assert rec.n_ticks == n   # nothing dropped

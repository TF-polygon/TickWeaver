"""Phase 2 — ChartHook ABC + Recorder unit tests."""

from __future__ import annotations

import pandas as pd

from tickweaver.core.types import Fill, OHLCBar, Side, Tick
from tickweaver.viz import ChartHook, EventRecorder, NullHook


def _bar(idx: int = 0) -> OHLCBar:
    return OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC")
        + pd.Timedelta(hours=idx),
        open=100.0,
        high=110.0,
        low=90.0,
        close=105.0,
        volume=10.0,
        symbol="T",
        timeframe="1h",
    )


def _tick(price: float = 100.0, idx: int = 0) -> Tick:
    return Tick(
        timestamp=pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(seconds=idx),
        price=price,
        bar_index=0,
        tick_index_in_bar=idx,
    )


def _fill() -> Fill:
    return Fill(
        order_id="X",
        symbol="T",
        side=Side.BUY,
        qty=1.0,
        price=100.0,
        fee=0.5,
        timestamp=pd.Timestamp("2024-01-01", tz="UTC"),
    )


# ─────────────────────────────────────────────────────────
# NullHook — no-op
# ─────────────────────────────────────────────────────────
def test_null_hook_subclass_of_chart_hook():
    assert issubclass(NullHook, ChartHook)


def test_null_hook_methods_are_noops():
    h = NullHook()
    h.on_init()
    h.on_bar(_bar(), 0)
    h.on_tick(_tick())
    h.on_fill(_fill())
    h.on_comment("test", 0)
    h.on_deinit(10000.0)
    # 통과만 하면 OK


# ─────────────────────────────────────────────────────────
# Recorder — capture events
# ─────────────────────────────────────────────────────────
def test_recorder_captures_all_event_types():
    rec = EventRecorder()
    rec.on_init()
    assert rec._init_called

    rec.on_bar(_bar(0), 0)
    rec.on_bar(_bar(1), 1)
    assert rec.n_bars == 2

    rec.on_tick(_tick(101.0, 1))
    rec.on_tick(_tick(102.0, 2))
    assert rec.n_ticks == 2

    rec.on_fill(_fill())
    assert rec.n_fills == 1

    rec.on_comment("status: long", 1)
    assert rec.n_comments == 1
    assert rec.comments[0].text == "status: long"
    assert rec.comments[0].bar_index == 1

    rec.on_deinit(10500.0)
    assert rec.final_equity == 10500.0
    assert rec._deinit_called


def test_recorder_max_ticks_bounded():
    rec = EventRecorder(max_ticks=3)
    for i in range(10):
        rec.on_tick(_tick(price=100.0 + i, idx=i))
    assert rec.n_ticks == 3
    # 마지막 3개만 보존됨
    last_prices = [t.price for t in rec.ticks]
    assert last_prices == [107.0, 108.0, 109.0]


def test_recorder_unbounded_when_max_ticks_none():
    rec = EventRecorder(max_ticks=None)
    for i in range(1000):
        rec.on_tick(_tick(idx=i))
    assert rec.n_ticks == 1000


def test_recorder_comment_attaches_last_bar_timestamp():
    rec = EventRecorder()
    rec.on_init()
    bar0 = _bar(0)
    rec.on_bar(bar0, 0)
    rec.on_comment("hi", 0)
    assert rec.comments[0].timestamp == bar0.timestamp


def test_recorder_comment_no_bar_yet_keeps_timestamp_none():
    rec = EventRecorder()
    rec.on_comment("first", 0)
    assert rec.comments[0].timestamp is None


def test_recorder_no_init_means_flag_false():
    rec = EventRecorder()
    assert rec._init_called is False
    assert rec._deinit_called is False
    assert rec.final_equity is None

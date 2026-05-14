"""Phase 2 — ChartHook ABC + Recorder unit tests.

Phase 1 (dev/adv_verbose) appends indicator-track tests for:
- IndicatorRegistrationEvent / IndicatorSampleEvent dataclasses
- ChartHook.on_indicator_register / on_indicator_sample
- EventRecorder.indicators (name-keyed dict of IndicatorTrack)
"""

from __future__ import annotations

import pandas as pd

from tickweaver.core.types import Fill, OHLCBar, Side, Tick
from tickweaver.viz import ChartHook, EventRecorder, NullHook
from tickweaver.viz.events import (
    IndicatorRegistrationEvent,
    IndicatorSampleEvent,
    IndicatorTrack,
)


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


# NullHook — no-op
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


# Recorder — capture events
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


# Phase 1 (dev/adv_verbose) — Indicator events + tracks
def test_indicator_registration_event_dataclass_fields():
    e = IndicatorRegistrationEvent(
        name="EMA20", panel="price", style={"color": "#FF9800"}
    )
    assert e.name == "EMA20"
    assert e.panel == "price"
    assert e.style == {"color": "#FF9800"}


def test_indicator_registration_default_style_is_empty():
    e = IndicatorRegistrationEvent(name="EMA20", panel="price")
    assert e.style == {}


def test_indicator_sample_event_dataclass_fields():
    ts = pd.Timestamp("2024-01-01 02:00:00", tz="UTC")
    s = IndicatorSampleEvent(name="EMA20", bar_index=5, timestamp=ts, value=100.5)
    assert s.name == "EMA20"
    assert s.bar_index == 5
    assert s.timestamp == ts
    assert s.value == 100.5


def test_indicator_track_holds_registration_and_samples():
    reg = IndicatorRegistrationEvent(name="X", panel="price", style={})
    t = IndicatorTrack(registration=reg, samples=[])
    assert t.registration == reg
    assert t.samples == []


def test_null_hook_indicator_methods_are_noops():
    h = NullHook()
    h.on_indicator_register(
        IndicatorRegistrationEvent(name="X", panel="price", style={})
    )
    h.on_indicator_sample(
        IndicatorSampleEvent(name="X", bar_index=0, timestamp=None, value=1.0)
    )


def test_recorder_indicators_starts_empty():
    rec = EventRecorder()
    assert rec.indicators == {}


def test_recorder_captures_indicator_registration():
    rec = EventRecorder()
    reg = IndicatorRegistrationEvent(
        name="EMA20", panel="price", style={"color": "#FFF"}
    )
    rec.on_indicator_register(reg)
    assert "EMA20" in rec.indicators
    assert rec.indicators["EMA20"].registration == reg
    assert rec.indicators["EMA20"].samples == []


def test_recorder_captures_indicator_samples_in_order():
    rec = EventRecorder()
    rec.on_indicator_register(
        IndicatorRegistrationEvent(name="EMA20", panel="price", style={})
    )
    s1 = IndicatorSampleEvent(name="EMA20", bar_index=0, timestamp=None, value=100.0)
    s2 = IndicatorSampleEvent(name="EMA20", bar_index=1, timestamp=None, value=101.0)
    rec.on_indicator_sample(s1)
    rec.on_indicator_sample(s2)
    samples = rec.indicators["EMA20"].samples
    assert len(samples) == 2
    assert samples[0] == s1
    assert samples[1] == s2


def test_recorder_sample_without_register_auto_creates_track():
    """api.plot fallback: sample 만으로도 트랙이 생겨야 (default panel='price')."""
    rec = EventRecorder()
    s = IndicatorSampleEvent(name="custom", bar_index=0, timestamp=None, value=42.0)
    rec.on_indicator_sample(s)
    assert "custom" in rec.indicators
    assert rec.indicators["custom"].registration.name == "custom"
    assert rec.indicators["custom"].registration.panel == "price"
    assert rec.indicators["custom"].registration.style == {}
    assert len(rec.indicators["custom"].samples) == 1
    assert rec.indicators["custom"].samples[0] == s


def test_recorder_duplicate_register_last_write_wins():
    rec = EventRecorder()
    rec.on_indicator_register(
        IndicatorRegistrationEvent(name="X", panel="price", style={"color": "red"})
    )
    rec.on_indicator_register(
        IndicatorRegistrationEvent(name="X", panel="price", style={"color": "blue"})
    )
    assert rec.indicators["X"].registration.style == {"color": "blue"}


def test_recorder_register_does_not_clear_existing_samples():
    """re-register 가 발생해도 기존 samples 는 보존."""
    rec = EventRecorder()
    rec.on_indicator_register(
        IndicatorRegistrationEvent(name="X", panel="price", style={})
    )
    rec.on_indicator_sample(
        IndicatorSampleEvent(name="X", bar_index=0, timestamp=None, value=1.0)
    )
    rec.on_indicator_register(
        IndicatorRegistrationEvent(name="X", panel="price", style={"color": "blue"})
    )
    assert len(rec.indicators["X"].samples) == 1
    assert rec.indicators["X"].registration.style == {"color": "blue"}


def test_recorder_multiple_panels_independent():
    rec = EventRecorder()
    rec.on_indicator_register(
        IndicatorRegistrationEvent(name="EMA20", panel="price", style={})
    )
    rec.on_indicator_register(
        IndicatorRegistrationEvent(name="RSI", panel="rsi", style={})
    )
    rec.on_indicator_sample(
        IndicatorSampleEvent(name="EMA20", bar_index=0, timestamp=None, value=100.0)
    )
    rec.on_indicator_sample(
        IndicatorSampleEvent(name="RSI", bar_index=0, timestamp=None, value=55.0)
    )
    assert len(rec.indicators["EMA20"].samples) == 1
    assert len(rec.indicators["RSI"].samples) == 1
    assert rec.indicators["EMA20"].registration.panel == "price"
    assert rec.indicators["RSI"].registration.panel == "rsi"

"""Phase 5.2 (dev/adv_verbose) — adversarial / bug-hunting tests.

These probe known fragile areas:
- bind_indicator double-call (append-only bindings list)
- NaN values propagating through samples
- numpy scalar types instead of Python floats
- auto-register followed by explicit register
- larger workloads (memory + time budgets)
"""

from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd

from tickweaver.execution.backtest_broker import BacktestBroker
from tickweaver.execution.fees import NoFee
from tickweaver.execution.slippage import NoSlippage
from tickweaver.strategy.api import StrategyAPI
from tickweaver.strategy.indicators import EMA, RSI, BollingerBands
from tickweaver.viz.events import (
    IndicatorRegistrationEvent,
    IndicatorSampleEvent,
)
from tickweaver.viz.hook import NullHook
from tickweaver.viz.recorder import EventRecorder


def _broker() -> BacktestBroker:
    return BacktestBroker(
        symbol="T",
        initial_cash=10_000.0,
        fee_model=NoFee(),
        slippage_model=NoSlippage(),
    )


class _Collector(NullHook):
    def __init__(self) -> None:
        self.registrations: list = []
        self.samples: list = []

    def on_indicator_register(self, reg):
        self.registrations.append(reg)

    def on_indicator_sample(self, s):
        self.samples.append(s)


def _api(chart_hook=None) -> StrategyAPI:
    return StrategyAPI(
        broker=_broker(),
        symbol="T",
        console_log=False,
        chart_hook=chart_hook,
    )


# ─────────────────────────────────────────────────────────
# A. bind_indicator 중복 호출
# ─────────────────────────────────────────────────────────
def test_bind_indicator_double_call_does_not_duplicate_bindings():
    """bind_indicator('EMA20', ema) 를 두 번 호출하면 _indicator_bindings 는
    한 번만 들어있어야 한다. 그렇지 않으면 매 bar 같은 sample 두 번 emit."""
    c = _Collector()
    api = _api(chart_hook=c)
    ema = EMA(period=3)
    for v in [10.0, 11.0, 12.0]:
        ema.update(v)
    api.bind_indicator("EMA20", ema)
    api.bind_indicator("EMA20", ema)  # 의도되지 않은 두 번째 호출
    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    samples_for_ema = [s for s in c.samples if s.name == "EMA20"]
    assert len(samples_for_ema) == 1, (
        f"expected 1 sample for EMA20 after duplicate bind, got {len(samples_for_ema)}"
    )


def test_bind_indicator_double_call_multi_value_does_not_duplicate():
    """Multi-value indicator (BB) 의 sub-line 들도 중복 bind 시 한 번만 emit."""
    c = _Collector()
    api = _api(chart_hook=c)
    bb = BollingerBands(period=3, mult=2.0)
    for v in [10.0, 11.0, 12.0]:
        bb.update(v)
    api.bind_indicator("BB", bb)
    api.bind_indicator("BB", bb)
    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    by_name = {}
    for s in c.samples:
        by_name[s.name] = by_name.get(s.name, 0) + 1
    for sub in ("BB.middle", "BB.upper", "BB.lower"):
        assert by_name.get(sub, 0) == 1, (
            f"expected 1 sample for {sub} after duplicate bind, got {by_name.get(sub, 0)}"
        )


# ─────────────────────────────────────────────────────────
# B. NaN sample 처리
# ─────────────────────────────────────────────────────────
def test_sample_indicators_skips_nan_value():
    """indicator.value 가 NaN 이면 sample 을 emit 하지 말아야 한다.
    그렇지 않으면 finplot 라인에 빈 구멍이나 spike."""
    c = _Collector()
    api = _api(chart_hook=c)

    class _NaNIndicator:
        PANEL = "price"
        SUBVALUES = None
        value = float("nan")

    api.bind_indicator("Bad", _NaNIndicator())
    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    # registration 한 번은 OK; sample 은 0개여야 한다.
    assert len(c.samples) == 0, (
        f"expected NaN to be skipped, got {len(c.samples)} samples"
    )


# ─────────────────────────────────────────────────────────
# C. numpy 스칼라 타입
# ─────────────────────────────────────────────────────────
def test_sample_indicators_accepts_numpy_float():
    """indicator 가 numpy.float64 / np.int64 같은 numpy 스칼라를 .value 로
    노출할 때 isinstance(raw, (int, float)) 가 True 인지 검증."""
    c = _Collector()
    api = _api(chart_hook=c)

    class _NumpyIndicator:
        PANEL = "price"
        SUBVALUES = None
        value = np.float64(123.45)

    api.bind_indicator("X", _NumpyIndicator())
    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    assert len(c.samples) == 1, "numpy.float64 must pass isinstance(int, float)"
    assert c.samples[0].value == 123.45


# ─────────────────────────────────────────────────────────
# D. auto-register → explicit register 갱신
# ─────────────────────────────────────────────────────────
def test_recorder_explicit_register_after_auto_register_updates_panel():
    """plot() 으로 auto-register (panel='price') 됐는데, 나중에 bind_indicator
    가 panel='X' 로 register 하면 panel 이 'X' 로 갱신돼야 한다."""
    rec = EventRecorder()
    # 1) auto-register via plot fallback path
    rec.on_indicator_sample(
        IndicatorSampleEvent(
            name="EMA20", bar_index=0, timestamp=None, value=100.0
        )
    )
    assert rec.indicators["EMA20"].registration.panel == "price"
    # 2) explicit register with different panel
    rec.on_indicator_register(
        IndicatorRegistrationEvent(name="EMA20", panel="custom", style={})
    )
    assert rec.indicators["EMA20"].registration.panel == "custom"
    # 3) 기존 sample 은 보존
    assert len(rec.indicators["EMA20"].samples) == 1


# ─────────────────────────────────────────────────────────
# E. 큰 데이터셋 + 많은 indicator (메모리 + 시간 budget)
# ─────────────────────────────────────────────────────────
def test_large_workload_5000_bars_10_indicators_within_budget():
    """5,000 bar × 10 indicator × per-bar sample 시나리오의 시간 budget.
    실제 환경에서 1년 1h × 10 indicator 정도. 1초 안에 끝나야."""
    c = _Collector()
    api = _api(chart_hook=c)

    # 10개 single-value indicator. Pre-warm each indicator past its
    # longest period so every per-bar sample is captured.
    indicators = []
    for i in range(10):
        ema = EMA(period=2 + i)
        for _ in range(30):
            ema.update(100.0)
        indicators.append(ema)
        api.bind_indicator(f"EMA{i}", ema)

    base_ts = pd.Timestamp("2024-01-01", tz="UTC")
    start = time.perf_counter()
    for i in range(5000):
        # 가벼운 update — 실제로 다 호출
        for ema in indicators:
            ema.update(100.0 + (i % 20) * 0.1)
        api._set_bar_context(i, base_ts + pd.Timedelta(hours=i))
        api._sample_indicators(i, base_ts + pd.Timedelta(hours=i))
    elapsed = time.perf_counter() - start

    # 50,000 samples emit (5000 bars × 10 indicators)
    assert len(c.samples) == 50_000
    # 시간 budget — 부하 회귀 잡기. 보수적으로 5초.
    assert elapsed < 5.0, f"workload took {elapsed:.2f}s, expected < 5s"


def test_recorder_indicators_memory_bounded_per_track():
    """N bars × N indicators 의 메모리 footprint 가 sample 개수에 선형."""
    rec = EventRecorder()
    rec.on_indicator_register(
        IndicatorRegistrationEvent(name="X", panel="price", style={})
    )
    base_ts = pd.Timestamp("2024-01-01", tz="UTC")
    for i in range(10_000):
        rec.on_indicator_sample(
            IndicatorSampleEvent(
                name="X",
                bar_index=i,
                timestamp=base_ts + pd.Timedelta(hours=i),
                value=100.0 + i * 0.01,
            )
        )
    assert len(rec.indicators["X"].samples) == 10_000


# ─────────────────────────────────────────────────────────
# F. crosshair lookup 부하 (마우스 움직임 시뮬레이션)
# ─────────────────────────────────────────────────────────
def test_crosshair_lookup_build_on_large_recorder_fast():
    """5,000 bars × 10 indicators × 5000 samples 인 recorder 에서
    _build_crosshair_lookup 호출이 1초 안에 끝나야 한다.
    이건 show_replay 진입 시 한 번 호출되는 경로."""
    from tickweaver.core.types import OHLCBar
    from tickweaver.viz.live_window import (
        _build_crosshair_lookup,
        _group_indicators_by_panel,
    )

    rec = EventRecorder()
    base_ts = pd.Timestamp("2024-01-01", tz="UTC")
    # 5000 bars
    for i in range(5_000):
        bar = OHLCBar(
            timestamp=base_ts + pd.Timedelta(hours=i),
            open=100.0, high=101.0, low=99.0, close=100.5,
            volume=1.0, symbol="T", timeframe="1h",
        )
        rec.on_bar(bar, i)
    # 10 indicators, 5000 samples each
    for k in range(10):
        rec.on_indicator_register(
            IndicatorRegistrationEvent(
                name=f"L{k}",
                panel="price" if k < 5 else "rsi",
                style={},
            )
        )
        for i in range(5_000):
            rec.on_indicator_sample(
                IndicatorSampleEvent(
                    name=f"L{k}",
                    bar_index=i,
                    timestamp=base_ts + pd.Timedelta(hours=i),
                    value=100.0 + (i * 0.01),
                )
            )

    grouped = _group_indicators_by_panel(rec)
    start = time.perf_counter()
    ohlc_lookup, panel_lookup = _build_crosshair_lookup(rec, grouped)
    elapsed = time.perf_counter() - start

    assert len(ohlc_lookup) == 5_000
    assert "price" in panel_lookup and "rsi" in panel_lookup
    assert len(panel_lookup["price"]) == 5_000
    assert elapsed < 1.0, f"lookup build took {elapsed:.2f}s, expected < 1s"


def test_crosshair_lookup_query_is_constant_time():
    """lookup 자체는 dict 조회라 O(1). 100k 회 조회가 1초 안에 끝나야."""
    from tickweaver.core.types import OHLCBar
    from tickweaver.viz.live_window import (
        _build_crosshair_lookup,
        _group_indicators_by_panel,
    )

    rec = EventRecorder()
    base_ts = pd.Timestamp("2024-01-01", tz="UTC")
    for i in range(1000):
        bar = OHLCBar(
            timestamp=base_ts + pd.Timedelta(hours=i),
            open=100.0, high=101.0, low=99.0, close=100.5,
            volume=1.0, symbol="T", timeframe="1h",
        )
        rec.on_bar(bar, i)
    grouped = _group_indicators_by_panel(rec)
    ohlc_lookup, _ = _build_crosshair_lookup(rec, grouped)

    timestamps = list(ohlc_lookup.keys())
    start = time.perf_counter()
    for _ in range(100_000):
        ts = timestamps[_ % len(timestamps)]
        _ = ohlc_lookup.get(ts)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"100k lookups took {elapsed:.2f}s, expected < 1s"


# ─────────────────────────────────────────────────────────
# Phase 5.2 round 2 — extra edge cases + heavier loads
# ─────────────────────────────────────────────────────────
def test_sample_indicators_skips_inf_value():
    """+inf / -inf must be treated like NaN — silently skipped."""
    c = _Collector()
    api = _api(chart_hook=c)

    class _InfIndicator:
        PANEL = "price"
        SUBVALUES = None
        value = float("inf")

    api.bind_indicator("Bad+", _InfIndicator())
    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))

    class _NegInf:
        PANEL = "price"
        SUBVALUES = None
        value = float("-inf")

    api.bind_indicator("Bad-", _NegInf())
    api._sample_indicators(1, pd.Timestamp("2024-01-01 01:00", tz="UTC"))
    assert len(c.samples) == 0


def test_sample_indicators_swallows_raising_property():
    """If indicator.value raises (bug in user code), _sample_indicators
    must not crash the backtest — log-and-skip is acceptable."""
    c = _Collector()
    api = _api(chart_hook=c)

    class _RaisingIndicator:
        PANEL = "price"
        SUBVALUES = None

        @property
        def value(self):
            raise RuntimeError("boom")

    api.bind_indicator("Boom", _RaisingIndicator())
    # The current implementation may or may not catch this — pin behaviour:
    # the call should not raise.
    try:
        api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    except Exception as e:
        # If it raises, fail loudly so we know to add a try/except in
        # _sample_indicators. Current implementation lets it propagate, which
        # is a quality risk for production strategies.
        import pytest
        pytest.fail(
            f"_sample_indicators must swallow indicator-side errors, "
            f"but raised {type(e).__name__}: {e}"
        )


def test_bind_indicator_after_indicator_reset_skips_sample():
    """After indicator.reset() the .value is None — sample must be skipped."""
    c = _Collector()
    api = _api(chart_hook=c)
    ema = EMA(period=3)
    for v in [10.0, 11.0, 12.0]:
        ema.update(v)
    api.bind_indicator("EMA", ema)
    # Warm sample
    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    n_after_warm = len(c.samples)
    # Reset and re-sample
    ema.reset()
    api._sample_indicators(1, pd.Timestamp("2024-01-01 01:00", tz="UTC"))
    # No new sample because .value is None again.
    assert len(c.samples) == n_after_warm


def test_bind_indicator_with_unicode_and_long_name():
    """Names with CJK, emoji, and 200 chars must work without crashing."""
    c = _Collector()
    api = _api(chart_hook=c)
    ema = EMA(period=2)
    ema.update(10.0)
    ema.update(11.0)

    cases = [
        "EMA 한국어",
        "EMA \U0001F4C8",  # 📈
        "x" * 200,
    ]
    for name in cases:
        api.bind_indicator(name, ema)

    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    names_in_samples = {s.name for s in c.samples}
    for name in cases:
        assert name in names_in_samples, f"missing sample for name={name!r}"


def test_recorder_handles_mixed_tz_naive_and_aware_samples():
    """Mixing tz-naive and tz-aware timestamps in samples must not crash
    the lookup builder. Build should tolerate both."""
    from tickweaver.viz.live_window import (
        _build_crosshair_lookup,
        _group_indicators_by_panel,
    )

    rec = EventRecorder()
    rec.on_indicator_register(
        IndicatorRegistrationEvent(name="X", panel="price", style={})
    )
    # mix: naive, then aware
    rec.on_indicator_sample(
        IndicatorSampleEvent(
            name="X",
            bar_index=0,
            timestamp=pd.Timestamp("2024-01-01"),  # naive
            value=1.0,
        )
    )
    rec.on_indicator_sample(
        IndicatorSampleEvent(
            name="X",
            bar_index=1,
            timestamp=pd.Timestamp("2024-01-01 01:00", tz="UTC"),
            value=2.0,
        )
    )
    grouped = _group_indicators_by_panel(rec)
    _, panel_lookup = _build_crosshair_lookup(rec, grouped)
    # Both samples must be retrievable.
    assert len(panel_lookup["price"]) == 2


def test_indicator_replacement_via_bind_different_indicator():
    """Strategy may re-bind the same name to a different indicator object.
    With the round-1 dedup (same name -> noop), the binding still points to
    the FIRST indicator. This pins that behaviour so callers know they need
    to use distinct names if they want to swap targets."""
    c = _Collector()
    api = _api(chart_hook=c)
    ema_a = EMA(period=2)
    ema_a.update(10.0)
    ema_a.update(11.0)  # value = 10.5
    ema_b = EMA(period=2)
    ema_b.update(100.0)
    ema_b.update(101.0)  # value = 100.5

    api.bind_indicator("EMA", ema_a)
    api.bind_indicator("EMA", ema_b)  # second call is idempotent → ema_a stays bound

    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    ema_samples = [s for s in c.samples if s.name == "EMA"]
    assert len(ema_samples) == 1
    # The bound indicator is still ema_a (the first one).
    assert ema_samples[0].value == ema_a.value
    assert ema_samples[0].value != ema_b.value


def test_heavy_workload_8760_bars_6_indicators_under_3s():
    """1 year × 1h × 6 indicators (real-world max for SMA/EMA/RSI/ATR/MACD/BB).
    Must finish per-bar sampling loop under 3 seconds."""
    c = _Collector()
    api = _api(chart_hook=c)

    # Use the actual indicator classes from the library.
    from tickweaver.strategy.indicators import (
        ATR,
        EMA,
        MACD,
        RSI,
        SMA,
        BollingerBands,
    )

    sma = SMA(period=20)
    ema = EMA(period=20)
    rsi = RSI(period=14)
    atr = ATR(period=14)
    macd = MACD(fast=12, slow=26, signal=9)
    bb = BollingerBands(period=20, mult=2.0)
    # Pre-warm
    for v in range(40):
        sma.update(100.0)
        ema.update(100.0)
        rsi.update(100.0 + v * 0.01)
        atr.update(101.0, 99.0, 100.0)
        macd.update(100.0)
        bb.update(100.0 + v * 0.01)

    api.bind_indicator("SMA", sma)
    api.bind_indicator("EMA", ema)
    api.bind_indicator("RSI", rsi)
    api.bind_indicator("ATR", atr)
    api.bind_indicator("MACD", macd)   # 3 sub-lines
    api.bind_indicator("BB", bb)        # 3 sub-lines

    base_ts = pd.Timestamp("2024-01-01", tz="UTC")
    start = time.perf_counter()
    for i in range(8760):
        x = 100.0 + (i % 50) * 0.1
        sma.update(x)
        ema.update(x)
        rsi.update(x)
        atr.update(x + 0.5, x - 0.5, x)
        macd.update(x)
        bb.update(x)
        api._set_bar_context(i, base_ts + pd.Timedelta(hours=i))
        api._sample_indicators(i, base_ts + pd.Timedelta(hours=i))
    elapsed = time.perf_counter() - start

    # 8760 bars × (4 single + 6 sub) = 87,600 samples (when warm)
    assert len(c.samples) >= 87_000
    assert elapsed < 3.0, f"heavy workload took {elapsed:.2f}s, expected < 3s"


def test_repeated_bind_calls_do_not_grow_bindings_list():
    """1000 redundant bind_indicator calls on the same name → list stays at 1."""
    c = _Collector()
    api = _api(chart_hook=c)
    ema = EMA(period=2)
    ema.update(10.0)
    ema.update(11.0)
    for _ in range(1000):
        api.bind_indicator("EMA", ema)
    assert len(api._indicator_bindings) == 1


def test_chart_hook_none_keeps_internal_state_clean():
    """When chart_hook is None, bind/plot/_sample_indicators must all be
    noops and not accumulate any state. This guarantees zero overhead when
    --viz is off."""
    api = _api(chart_hook=None)
    ema = EMA(period=2)
    ema.update(10.0)
    ema.update(11.0)
    api.bind_indicator("EMA", ema)
    api.bind_indicator("EMA", ema)
    api._set_bar_context(0, pd.Timestamp("2024-01-01", tz="UTC"))
    api.plot("custom", 42.0)
    api._sample_indicators(0, pd.Timestamp("2024-01-01", tz="UTC"))
    # No state should have accumulated.
    assert api._indicator_bindings == []
    assert api._plot_registered == set()


def test_plot_with_nan_value_still_passes_through():
    """api.plot() emits whatever the caller hands it. Unlike bind_indicator's
    auto-sampling (which can filter), plot() is explicit -- pin that NaN
    values reach the hook as-is so caller has the choice."""
    c = _Collector()
    api = _api(chart_hook=c)
    api._set_bar_context(0, pd.Timestamp("2024-01-01", tz="UTC"))
    api.plot("signal", float("nan"))
    # Sample fired even with NaN — caller's responsibility.
    assert len(c.samples) == 1
    assert math.isnan(c.samples[0].value)


def test_build_crosshair_lookup_with_empty_recorder():
    """show_replay path: empty recorder still produces valid (empty) lookup."""
    from tickweaver.viz.live_window import (
        _build_crosshair_lookup,
        _group_indicators_by_panel,
    )

    rec = EventRecorder()
    grouped = _group_indicators_by_panel(rec)
    ohlc, panel_lookup = _build_crosshair_lookup(rec, grouped)
    assert ohlc == {}
    assert "price" in panel_lookup
    assert panel_lookup["price"] == {}
